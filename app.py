import os
import re
from pathlib import Path

import requests
import streamlit as st
from google import genai
from supabase import create_client

from model import predict as model_predict

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
PREDICT_WORDS = ("predict", "prediction", "who will win", "chances", "probability")
TABLE_WORDS = ("table", "standings", "position")
FIXTURE_WORDS = ("fixture", "upcoming", "next match", "schedule")
RESULT_WORDS = ("result", "score", "latest")
TERMS_FILE = Path(__file__).parent / "terms.md"

st.markdown(
    """
    <style>
    .block-container {max-width: 780px; padding-top: 1.5rem;}
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


@st.cache_data(ttl=600, show_spinner=False)
def load_matches(code):
    return fd_get(f"competitions/{code}/matches")


@st.cache_data(ttl=600, show_spinner=False)
def load_table(code):
    return fd_get(f"competitions/{code}/standings")


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
IS_OWNER = bool(get_secret("ADMIN_EMAIL")) and EMAIL == get_secret("ADMIN_EMAIL").strip().lower()


# ---------- Database helpers ----------
def ensure_account(email):
    sb = db()
    sb.table("users").upsert({"email": email}, on_conflict="email").execute()
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
        ensure_account(EMAIL)
        st.session_state.account_ready = True
    except Exception as e:
        st.error(f"Could not load your account: {e}")
        st.stop()


# ---------- Manual PayBill and access codes ----------
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


def manual_payment_steps():
    paybill = get_secret("PAYBILL_NUMBER")
    account = get_secret("ACCOUNT_NUMBER")
    if not paybill or not account:
        st.info("Payment details are not set up yet. Please check back soon.")
        return
    st.markdown(
        f"""
**Buy {PACK_CREDITS} credits for KSh {PACK_PRICE_KES}**

1. Go to **M-Pesa → Lipa na M-Pesa → Pay Bill**
2. Business number: **{paybill}**
3. Account number: **{account}**
4. Amount: **KSh {PACK_PRICE_KES}**
5. Enter your M-Pesa PIN and confirm.
6. Send us the M-Pesa confirmation code and your email. Credits are added after we check the payment.
"""
    )


def payment_panel(suffix):
    """PayBill steps plus the access-code form. Use a different suffix for each place on the page."""
    manual_payment_steps()
    with st.form(f"redeem_{suffix}"):
        code_in = st.text_input("Or enter an access code", key=f"code_{suffix}")
        if st.form_submit_button("Redeem code"):
            redeem_code(code_in.strip())


def owner_credit(buyer, ref, packs):
    buyer = buyer.strip().lower()
    ref = ref.strip().upper()
    if "@" not in buyer or not ref:
        st.error("Enter the buyer's email and the M-Pesa confirmation code.")
        return
    sb = db()
    marker = f"MPESA:{ref}"
    if sb.table("redemptions").select("code").eq("code", marker).execute().data:
        st.error(f"Code {ref} has already been credited.")
        return
    ensure_account(buyer)
    change_credits(buyer, int(packs) * PACK_CREDITS, f"PayBill {ref}")
    sb.table("redemptions").insert({"code": marker, "email": buyer}).execute()
    st.success(f"Added {int(packs) * PACK_CREDITS} credits to {buyer}.")


# ---------- Football helpers ----------
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


def detect_league(lower):
    for name, code in COMPETITIONS.items():
        if name.lower() in lower:
            return code
    return "PL"


def table_text(code):
    try:
        standings = load_table(code).get("standings", [])
        rows = standings[0].get("table", []) if standings else []
        lines = [
            f"{r['position']}. {r['team']['name']} · {r['playedGames']} played · {r['points']} pts"
            for r in rows
        ]
        return "**Table**\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not load the table: {e}"


def fixtures_text(code):
    try:
        matches = load_matches(code).get("matches", [])
        upcoming = [x for x in matches if x.get("status") in ("SCHEDULED", "TIMED")][:10]
        if not upcoming:
            return "No upcoming fixtures found."
        lines = [
            f"{(x.get('utcDate') or '')[:16].replace('T', ' ')} UTC · {x['homeTeam']['name']} vs {x['awayTeam']['name']}"
            for x in upcoming
        ]
        return "**Upcoming fixtures**\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not load fixtures: {e}"


def results_text(code):
    try:
        matches = load_matches(code).get("matches", [])
        recent = [x for x in matches if x.get("status") == "FINISHED"][-10:]
        if not recent:
            return "No recent results found."
        lines = []
        for x in reversed(recent):
            s = x.get("score", {}).get("fullTime", {})
            lines.append(f"{x['homeTeam']['name']} {s.get('home')} - {s.get('away')} {x['awayTeam']['name']}")
        return "**Recent results**\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Could not load results: {e}"


def chat_reply(text):
    history = st.session_state.messages[-6:]
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = (
        "You are the football assistant in the Matchday Prediction app. Chat freely about football. "
        "Do not give match predictions or odds here. Keep answers short.\n\n"
        f"Conversation so far:\n{convo}\nuser: {text}"
    )
    try:
        return gemini().models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    except Exception as e:
        return f"Sorry, I could not answer that right now ({e})."


def prediction_text(text, balance):
    m = re.match(r"^\s*(?:predict\s+)?(.+?)\s+(?:vs\.?|v)\s+(.+?)\s*$", text, re.IGNORECASE)
    if not m:
        return "Type the match like this: **predict Arsenal vs Chelsea**."
    code = detect_league(text.lower())
    try:
        matches = load_matches(code).get("matches", [])
    except Exception as e:
        return f"Could not load fixtures: {e}"
    teams = teams_from(matches)
    home = find_team(m.group(1), teams)
    away = find_team(m.group(2), teams)
    if not home or not away:
        return "I could not find both teams in that league. Check the spelling, or mention the league."
    if balance < PREDICTION_COST:
        st.session_state.wants_predict = True
        return (
            f"A prediction costs {PREDICTION_COST} credit and you have {balance}. "
            f"Buy a pack below or enter an access code, then ask again."
        )
    finished = [x for x in matches if x.get("status") == "FINISHED"]
    figures = model_predict(finished, home["id"], away["id"])
    if figures is None:
        return "Not enough match history for one of these teams yet. No credit was charged."

    change_credits(EMAIL, -PREDICTION_COST, "prediction")
    st.session_state.wants_predict = False
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
    try:
        resp = gemini().models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                f"Write a short, friendly preview of {home['name']} vs {away['name']}. "
                f"Use these exact figures: {home['name']} win {figures['p_home']:.0%}, "
                f"draw {figures['p_draw']:.0%}, {away['name']} win {figures['p_away']:.0%}. "
                "Explain the reasons in plain language. Do not promise a result or suggest betting."
            ),
        )
        explanation = resp.text
    except Exception as e:
        explanation = f"(Explanation unavailable right now: {e})"
    return (
        f"**{home['name']} vs {away['name']}**\n\n"
        f"- {home['name']} win: **{figures['p_home']:.0%}**\n"
        f"- Draw: **{figures['p_draw']:.0%}**\n"
        f"- {away['name']} win: **{figures['p_away']:.0%}**\n\n"
        f"{explanation}\n\n_1 credit used._"
    )


def answer(text, balance):
    lower = text.lower()
    code = detect_league(lower)
    if any(w in lower for w in PREDICT_WORDS):
        return prediction_text(text, balance)
    if any(w in lower for w in TABLE_WORDS):
        return table_text(code)
    if any(w in lower for w in FIXTURE_WORDS):
        return fixtures_text(code)
    if any(w in lower for w in RESULT_WORDS):
        return results_text(code)
    return chat_reply(text)


# ---------- Load balance ----------
try:
    balance = get_balance(EMAIL)
except Exception:
    balance = 0


# ---------- Sidebar ----------
with st.sidebar:
    st.header("Account")
    st.caption(f"{NAME}\n\n{EMAIL}")
    st.metric("Credits", balance)
    st.caption(f"1 prediction = {PREDICTION_COST} credit")
    st.subheader("Buy credits")
    st.caption(f"{PACK_CREDITS} credits for KSh {PACK_PRICE_KES}")
    payment_panel("side")

    if IS_OWNER:
        with st.expander("Owner: credit a PayBill payment"):
            with st.form("owner_credit_form"):
                buyer_in = st.text_input("Buyer's email")
                ref_in = st.text_input("M-Pesa confirmation code")
                packs_in = st.number_input("Packs (KSh 100 each)", min_value=1, max_value=20, value=1, step=1)
                if st.form_submit_button("Add credits"):
                    owner_credit(buyer_in, ref_in, packs_in)

    with st.expander("Terms"):
        if TERMS_FILE.exists():
            st.markdown(TERMS_FILE.read_text(encoding="utf-8"))
        else:
            st.write("Terms are not available.")
    st.caption("Predictions are estimates for entertainment. They are not betting advice.")
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()


# ---------- Chat ----------
st.title("⚽ Matchday Prediction")

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": f"Hi {NAME}! Ask me anything about football."}
    ]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if st.session_state.get("wants_predict") and balance < PREDICTION_COST:
    with st.container(border=True):
        st.warning(f"You have {balance} credits. A prediction needs {PREDICTION_COST}.")
        payment_panel("main")

prompt = st.chat_input("Ask about football")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    reply = answer(prompt, balance)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
