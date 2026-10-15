import os
import re
from pathlib import Path

import requests
import streamlit as st
from google import genai
from supabase import create_client

from model import predict as model_predict
from mpesa import normalise_phone, stk_push

st.set_page_config(page_title="Matchday Prediction", page_icon="⚽", layout="centered")

PACK_CREDITS = 5
PACK_PRICE_KES = 100
PREDICTION_COST = 1
GEMINI_MODEL = "gemini-2.5-flash"
COMPETITIONS = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Champions League": "CL",
}
TERMS_FILE = Path(__file__).parent / "terms.md"

st.markdown(
    """
    <style>
    .block-container {max-width: 780px; padding-top: 1.5rem;}
    .small-text {font-size: 0.8rem; opacity: 0.8;}
    </style>
    """,
    unsafe_allow_html=True,
)


def get_secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


@st.cache_resource
def db():
    return create_client(get_secret("SUPABASE_URL"), get_secret("SUPABASE_SECRET_KEY"))


@st.cache_resource
def gemini():
    return genai.Client(api_key=get_secret("GEMINI_API_KEY"))


@st.cache_data(ttl=600, show_spinner=False)
def fd_get(path):
    r = requests.get(
        f"https://api.football-data.org/v4/{path}",
        headers={"X-Auth-Token": get_secret("FOOTBALL_API_KEY")},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ---------- Login (typed email, no Google, no terms or age gate) ----------
if "email" not in st.session_state:
    st.title("⚽ Matchday Prediction")
    with st.form("login_form"):
        email_in = st.text_input("Email")
        name_in = st.text_input("Name (optional)")
        if st.form_submit_button("Continue", type="primary"):
            if "@" not in email_in:
                st.error("Enter a valid email address.")
            else:
                st.session_state.email = email_in.strip().lower()
                st.session_state.name = name_in.strip() or email_in.strip().lower()
                st.rerun()
    st.stop()

EMAIL = st.session_state.email
NAME = st.session_state.name


# ---------- Database helpers ----------
def ensure_account(email, name):
    sb = db()
    sb.table("users").upsert({"email": email, "name": name}, on_conflict="email").execute()
    sb.table("wallet").upsert(
        {"email": email, "credits": 0}, on_conflict="email", ignore_duplicates=True
    ).execute()


def get_balance(email):
    r = db().table("wallet").select("credits").eq("email", email).execute()
    return r.data[0]["credits"] if r.data else 0


def change_credits(email, delta, reason):
    sb = db()
    new_balance = get_balance(email) + delta
    sb.table("wallet").update({"credits": new_balance}).eq("email", email).execute()
    sb.table("ledger").insert({"email": email, "delta": delta, "reason": reason}).execute()


if not st.session_state.get("account_ready"):
    try:
        ensure_account(EMAIL, NAME)
        st.session_state.account_ready = True
    except Exception as e:
        st.error(f"Could not load your account: {e}")
        st.stop()


# ---------- Payments and access codes ----------
def start_payment(phone):
    try:
        msisdn = normalise_phone(phone)
    except Exception:
        st.error("Enter a valid Safaricom number, e.g. 0712345678.")
        return
    try:
        resp = stk_push(msisdn, PACK_PRICE_KES, f"Credits {PACK_CREDITS}")
    except Exception as e:
        st.error(f"Could not start M-Pesa payment: {e}")
        return
    checkout_id = resp.get("CheckoutRequestID")
    if not checkout_id:
        st.error(resp.get("errorMessage") or "M-Pesa did not accept the request. Try again.")
        return
    db().table("mpesa_payments").insert(
        {
            "checkout_request_id": checkout_id,
            "email": EMAIL,
            "amount": PACK_PRICE_KES,
            "status": "pending",
        }
    ).execute()
    st.info("Enter your M-Pesa PIN on your phone. Credits are added automatically once payment is confirmed.")


def redeem_code(code):
    codes = [c.strip() for c in get_secret("ACCESS_CODES").split(",") if c.strip()]
    if code not in codes:
        st.error("That access code is not valid.")
        return
    sb = db()
    used = sb.table("redemptions").select("code").eq("code", code).execute()
    if used.data:
        st.error("That access code has already been used.")
        return
    sb.table("redemptions").insert({"code": code, "email": EMAIL}).execute()
    change_credits(EMAIL, PACK_CREDITS, "access code")
    st.success(f"Added {PACK_CREDITS} credits.")


# ---------- Football data helpers ----------
@st.cache_data(ttl=600, show_spinner=False)
def load_matches(code):
    return fd_get(f"competitions/{code}/matches")


@st.cache_data(ttl=600, show_spinner=False)
def load_table(code):
    return fd_get(f"competitions/{code}/standings")


def teams_from(matches):
    teams = {}
    for m in matches:
        for side in ("homeTeam", "awayTeam"):
            t = m.get(side) or {}
            if t.get("id"):
                teams[t["id"]] = {
                    "id": t["id"],
                    "name": t.get("name", ""),
                    "short": t.get("shortName", "") or "",
                    "tla": t.get("tla", "") or "",
                }
    return list(teams.values())


def find_team(query, teams):
    q = query.strip().lower()
    if not q:
        return None
    for t in teams:
        if q in (t["name"].lower(), t["short"].lower(), t["tla"].lower()):
            return t
    for t in teams:
        if q in t["name"].lower() or q in t["short"].lower():
            return t
    return None


def explain(home, away, figures):
    prompt = (
        f"Write a short, friendly match preview of {home} vs {away} for a football fan. "
        f"Model probabilities: {home} win {figures['p_home']:.0%}, draw {figures['p_draw']:.0%}, "
        f"{away} win {figures['p_away']:.0%}. Use these exact figures, explain the reasons "
        f"in plain language, and do not promise a result or suggest betting."
    )
    try:
        resp = gemini().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return resp.text
    except Exception as e:
        return f"(Explanation unavailable right now: {e})"


def run_prediction(text, code):
    m = re.match(r"^\s*(.+?)\s+(?:vs\.?|v)\s+(.+?)\s*$", text, re.IGNORECASE)
    if not m:
        st.warning("Use the format: Team A vs Team B")
        return
    try:
        data = load_matches(code)
    except Exception as e:
        st.error(f"Could not load fixtures: {e}")
        return
    matches = data.get("matches", [])
    teams = teams_from(matches)
    home = find_team(m.group(1), teams)
    away = find_team(m.group(2), teams)
    if not home or not away:
        st.warning("I could not find both teams in this league.")
        return
    if get_balance(EMAIL) < PREDICTION_COST:
        st.error("You need credits to predict. Buy a pack or redeem an access code.")
        return
    finished = [x for x in matches if x.get("status") == "FINISHED"]
    figures = model_predict(finished, home["id"], away["id"])
    if figures is None:
        st.info("Not enough match history for one of these teams yet. No credit was charged.")
        return

    change_credits(EMAIL, -PREDICTION_COST, "prediction")
    db().table("predictions").insert(
        {
            "email": EMAIL,
            "home": home["name"],
            "away": away["name"],
            "p_home": figures["p_home"],
            "p_draw": figures["p_draw"],
            "p_away": figures["p_away"],
        }
    ).execute()

    st.subheader(f"{home['name']} vs {away['name']}")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{home['short'] or home['name']} win", f"{figures['p_home']:.0%}")
    c2.metric("Draw", f"{figures['p_draw']:.0%}")
    c3.metric(f"{away['short'] or away['name']} win", f"{figures['p_away']:.0%}")
    st.write(explain(home["name"], away["name"], figures))


# ---------- Sidebar ----------
with st.sidebar:
    st.header("Account")
    st.caption(f"{NAME}\n\n{EMAIL}")
    try:
        balance = get_balance(EMAIL)
    except Exception:
        balance = 0
    st.metric("Credits", balance)
    st.caption(f"1 prediction = {PREDICTION_COST} credit")

    st.subheader(f"Buy {PACK_CREDITS} credits")
    st.caption(f"KSh {PACK_PRICE_KES} via M-Pesa")
    with st.form("buy_pack"):
        phone = st.text_input("M-Pesa phone number", placeholder="0712345678")
        if st.form_submit_button(f"Pay KSh {PACK_PRICE_KES}"):
            start_payment(phone)

    with st.form("redeem"):
        code = st.text_input("Access code")
        if st.form_submit_button("Redeem"):
            redeem_code(code.strip())

    with st.expander("Terms"):
        if TERMS_FILE.exists():
            st.markdown(TERMS_FILE.read_text(encoding="utf-8"))
        else:
            st.write("Terms are not available.")
    st.caption("Predictions are estimates for entertainment. They are not betting advice.")

    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()


# ---------- Main ----------
st.title("⚽ Matchday Prediction")
league = st.selectbox("League", list(COMPETITIONS.keys()))
code = COMPETITIONS[league]

tab_predict, tab_fixtures, tab_table = st.tabs(["Predict", "Fixtures", "Table"])

with tab_predict:
    st.write("Type a match, for example **Arsenal vs Chelsea**. Each prediction uses 1 credit.")
    with st.form("predict_form"):
        match_text = st.text_input("Match", placeholder="Arsenal vs Chelsea")
        submitted = st.form_submit_button("Predict", type="primary")
    if submitted:
        run_prediction(match_text, code)

with tab_fixtures:
    try:
        matches = load_matches(code).get("matches", [])
        upcoming = [x for x in matches if x.get("status") in ("SCHEDULED", "TIMED")][:20]
        recent = [x for x in matches if x.get("status") == "FINISHED"][-10:]
        st.subheader("Upcoming")
        if not upcoming:
            st.write("No upcoming fixtures.")
        for x in upcoming:
            when = (x.get("utcDate") or "")[:16].replace("T", " ")
            st.write(f"{when} UTC · {x['homeTeam']['name']} vs {x['awayTeam']['name']}")
        st.subheader("Recent results")
        for x in reversed(recent):
            score = x.get("score", {}).get("fullTime", {})
            st.write(
                f"{x['homeTeam']['name']} {score.get('home')} - {score.get('away')} {x['awayTeam']['name']}"
            )
    except Exception as e:
        st.error(f"Could not load fixtures: {e}")

with tab_table:
    try:
        standings = load_table(code).get("standings", [])
        rows = standings[0].get("table", []) if standings else []
        st.dataframe(
            [
                {
                    "Pos": r.get("position"),
                    "Team": r.get("team", {}).get("name"),
                    "P": r.get("playedGames"),
                    "W": r.get("won"),
                    "D": r.get("draw"),
                    "L": r.get("lost"),
                    "GD": r.get("goalDifference"),
                    "Pts": r.get("points"),
                }
                for r in rows
            ],
            hide_index=True,
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Could not load the table: {e}")
