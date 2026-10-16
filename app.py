import os
import io
import re
import math
import wave
import struct
import html
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import requests
import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client
from model import predict as model_predict


def get_secret(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return default


ADMIN_EMAIL = get_secret("ADMIN_EMAIL").strip().lower()


def is_owner(email):
    return bool(ADMIN_EMAIL) and email == ADMIN_EMAIL


MODEL = "gemini-flash-lite-latest"          # analysis model
TRANSCRIBE_MODEL = "gemini-flash-latest"    # speech to text
TTS_MODEL = "gemini-2.5-flash-preview-tts"  # text to speech (voice replies)
VOICE_NAME = "Kore"
CHAT_HEIGHT = 340
REPLY_MODES = ["Text", "Voice", "Both"]
ATTACH_TYPES = ["png", "jpg", "jpeg", "webp", "pdf"]
APP_NAME = "Matchday Prediction"
APP_TITLE = f"⚽ {APP_NAME}"
APP_TAGLINE = "Fixtures, form, and match analysis across top leagues. Ask by text, voice, or screenshot."
APP_ROLE_TAG = "Match Analyst"
HISTORY_LIMIT = 20
PACK_SIZE = 5             # prediction credits per pack
CREDIT_KSH = 20           # shillings per prediction credit
REFERRAL_CREDITS = 1      # free credits to the referrer when a referred friend's first pack is credited
NEW_CHAT_TITLE = "New chat"
EAT = timezone(timedelta(hours=3))  # Nairobi time
RECENT_N = 8        # finished matches per team used for form
H2H_N = 5           # head-to-head meetings to show

LEAGUES = {
    "Premier League (England)": "PL",
    "Serie A (Italy)": "SA",
    "La Liga (Spain)": "PD",
    "Bundesliga (Germany)": "BL1",
    "Ligue 1 (France)": "FL1",
    "Champions League": "CL",
}

QUICK_ACTIONS = [
    ("📅 Upcoming fixtures", "What are the upcoming fixtures in this league?"),
    ("🏆 League table", "Show me the current table and who is in the top 4."),
    ("📋 Recent results", "Show the recent results of all leagues."),
    ("🎯 My predictions", "What were my predictions and their outcomes?"),
    ("🔥 Best form", "Which teams have the best form right now?"),
    ("🔮 Predict a match", "Predict the next match of the top team in the table."),
]

# Words that mean the user wants a prediction (costs one credit)
PAID_KEYWORDS = [
    "predict", "prediction", "probab", "estimate", "chance", "odds",
    "forecast", "who will win", "who wins", "likely", "win probability", "%",
    "stronger", "better", "beat", "win",
]

# Words that mean a general question (free)
GENERAL_KEYWORDS = [
    "table", "fixture", "fixtures", "form", "schedule", "explain",
    "history", "head to head", "standings",
]

st.set_page_config(page_title=APP_NAME, page_icon="⚽", layout="centered")

st.markdown("""
<style>
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }
.stApp { background: #EFF6FF; }
.block-container { max-width: 780px; padding-top: 1rem; padding-bottom: 0.5rem; }
div[data-testid="stVerticalBlock"] { gap: 0.5rem; }
div[data-testid="stMarkdownContainer"] p { margin-bottom: 0; }

div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0.4rem !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] { min-width: 0 !important; }
div[data-testid="stHorizontalBlock"] div[data-testid="stPopover"] button,
div[data-testid="stHorizontalBlock"] .stButton > button {
    min-height: 2.5rem; width: 100%;
}

.brand {
    display: flex; align-items: center; gap: 14px;
    background: linear-gradient(135deg, #1E40AF 0%, #1D4ED8 100%);
    border-radius: 16px; padding: 12px 18px; margin-bottom: 6px;
    box-shadow: 0 4px 14px rgba(29, 78, 216, 0.20);
}
.brand-title { color: #FFFFFF; font-size: 1.3rem; font-weight: 700; margin: 0; }
.brand-sub { color: #DBEAFE; font-size: 0.88rem; margin: 2px 0 0 0; }
.brand-badge {
    margin-left: auto; background: #FACC15; color: #422006;
    font-size: 0.7rem; font-weight: 700; padding: 3px 9px; border-radius: 999px;
    white-space: nowrap;
}
.disclaimer { color: #64748B; font-size: 0.78rem; margin: 2px 0 4px 0; }
.quick-title { color: #1E3A8A; font-weight: 700; font-size: 0.95rem; margin: 10px 0 4px 0; }

.hero {
    background: #FFFFFF; border: 1px solid #BFDBFE; border-radius: 16px;
    padding: 14px 16px; margin: 6px 0 8px 0; box-shadow: 0 2px 8px rgba(29,78,216,0.08);
}
.hero h3 { color: #1E3A8A; margin: 0 0 4px 0; font-size: 1.05rem; }
.hero p { color: #475569; margin: 0; font-size: 0.88rem; line-height: 1.45; }
.steps { display: flex; gap: 8px; margin: 8px 0 0 0; }
.step {
    flex: 1; background: #DBEAFE; border-radius: 12px; padding: 10px;
    color: #1E3A8A; font-size: 0.8rem; line-height: 1.35;
}
.step b { display: block; font-size: 0.9rem; margin-bottom: 2px; }
.fx {
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
    background: #FFFFFF; border: 1px solid #DBEAFE; border-radius: 12px;
    padding: 8px 12px; margin: 5px 0; font-size: 0.88rem; color: #1E3A8A;
}
.fx-date { color: #64748B; font-size: 0.78rem; white-space: nowrap; }

.dtable-wrap { overflow-x: auto; background: #FFFFFF; border-radius: 12px; padding: 6px; margin: 6px 0; border: 1px solid #BFDBFE; }
.dtable { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.dtable th { background: #1D4ED8; color: #FFFFFF; padding: 6px 4px; text-align: center; white-space: nowrap; }
.dtable td { padding: 6px 4px; text-align: center; color: #1E3A8A; border-bottom: 1px solid #DBEAFE; white-space: nowrap; }
.dtable td.name { text-align: left; font-weight: 600; }
.dtable tr:nth-child(even) td { background: #F8FBFF; }

.tcard {
    background: #FFFFFF; border: 1px solid #BFDBFE; border-radius: 14px;
    padding: 12px 14px; margin: 8px 0; box-shadow: 0 2px 6px rgba(29,78,216,0.06);
}
.tcard-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.tcard-name { color: #1E3A8A; font-weight: 700; font-size: 1rem; }
.tcard-badge { background: #DBEAFE; color: #1E3A8A; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
.tcard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; margin-top: 8px; font-size: 0.82rem; color: #334155; }
.tcard-grid b { color: #1E3A8A; }
.tcard-form { margin-top: 8px; font-size: 0.82rem; color: #334155; }
.tcard-form span { display: inline-block; width: 22px; height: 22px; line-height: 22px; text-align: center; border-radius: 6px; color: #FFFFFF; font-weight: 700; font-size: 0.72rem; margin-right: 3px; }
.f-w { background: #16A34A; } .f-d { background: #94A3B8; } .f-l { background: #DC2626; }
.pbox { background: #FFFFFF; border: 1px solid #BFDBFE; border-radius: 14px; padding: 12px 14px; margin: 8px 0; font-size: 0.86rem; color: #334155; line-height: 1.6; }
.pbox-title { color: #1E3A8A; font-weight: 700; margin-bottom: 6px; }
.pbox b { color: #1E3A8A; }
.pbar-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 0.84rem; color: #1E3A8A; }
.pbar-row span { width: 110px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pbar { flex: 1; background: #DBEAFE; border-radius: 999px; height: 10px; overflow: hidden; }
.pfill { background: #1D4ED8; height: 100%; border-radius: 999px; }
.pbar-row b { width: 42px; text-align: right; }

.row { display: flex; align-items: flex-end; gap: 8px; margin: 6px 0; }
.row-user { justify-content: flex-end; }
.row-bot { justify-content: flex-start; }
.avatar {
    width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.7rem; font-weight: 700;
}
.avatar-bot { background: #1D4ED8; color: #FFFFFF; }
.avatar-user { background: #FACC15; color: #422006; }
.bubble {
    padding: 8px 12px; line-height: 1.45; font-size: 0.95rem;
    max-width: 78%; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.bubble-user {
    background: #FFFFFF; color: #1E3A8A;
    border: 1px solid #BFDBFE; border-left: 3px solid #FACC15;
    border-radius: 14px 14px 4px 14px;
}
.bubble-bot {
    background: #1D4ED8; color: #EFF6FF;
    border-radius: 14px 14px 14px 4px;
}

.stRadio > div { gap: 6px; }
.stRadio label p { font-weight: 600; color: #1E3A8A; font-size: 0.88rem; }
.stButton > button {
    background: #FFFFFF; color: #1E3A8A; border: 1px solid #93C5FD; font-weight: 600;
    border-radius: 10px; padding: 0.25rem 0.6rem;
}
.stButton > button:hover { background: #DBEAFE; color: #1E3A8A; border-color: #3B82F6; }
.stTextInput input { border-radius: 10px; padding: 0.4rem 0.6rem; }
div[data-testid="stPopover"] button { border-radius: 10px; padding: 0.25rem 0.5rem; }
.attach-note { color: #1D4ED8; font-size: 0.82rem; font-weight: 600; margin: 0; }
</style>
""", unsafe_allow_html=True)

# ---------- Session state ----------
st.session_state.setdefault("user_email", None)
st.session_state.setdefault("user_name", None)
st.session_state.setdefault("conv_id", None)
st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_audio", None)
st.session_state.setdefault("paywall", False)
st.session_state.setdefault("pending_voice", None)
st.session_state.setdefault("to_send", "")
st.session_state.setdefault("draft", "")
st.session_state.setdefault("reply_mode", "Text")
st.session_state.setdefault("league", list(LEAGUES.keys())[0])
st.session_state.setdefault("att_n", 0)
st.session_state.setdefault("visit_logged", False)
st.session_state.setdefault("resolved", False)
st.session_state.setdefault("lang", "en")
st.session_state.setdefault("restored", False)
st.session_state.setdefault("token", None)

# ---------- Header ----------
st.markdown(f"""
<div class="brand">
    <div>
        <p class="brand-title">{APP_TITLE}</p>
        <p class="brand-sub">{APP_TAGLINE}</p>
    </div>
    <span class="brand-badge">{APP_ROLE_TAG}</span>
</div>
""", unsafe_allow_html=True)

# ---------- Database (Supabase) ----------
@st.cache_resource
def get_db():
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_SECRET_KEY")
    if not url or not key:
        return None
    return create_client(url, key)

sb = get_db()
if sb is None:
    st.error("The app is not set up yet (database secrets missing).")
    st.stop()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def count_rows(table, **eq):
    q = sb.table(table).select("*", count="exact", head=True)
    for col, val in eq.items():
        q = q.eq(col, val)
    return q.execute().count or 0

def log_event(kind, email=None):
    sb.table("events").insert({"kind": kind, "email": email, "created": now_iso()}).execute()

def count_events(kind, days=None):
    q = sb.table("events").select("*", count="exact", head=True).eq("kind", kind)
    if days:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q = q.gte("created", since)
    return q.execute().count or 0

def count_unique_signins():
    rows = sb.table("events").select("email").eq("kind", "signin").execute().data
    return len({r["email"] for r in rows if r.get("email")})

def sign_in(email, username):
    """Returns (ok, message). Creates the account the first time an email is used and saves the username."""
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        return False, "Please enter a valid email address."
    existing = sb.table("users").select("email").eq("email", email).execute().data
    if existing:
        sb.table("users").update({"username": username}).eq("email", email).execute()
    else:
        sb.table("users").insert({
            "email": email,
            "username": username,
            "ref_code": secrets.token_hex(4).upper(),
            "created": now_iso(),
        }).execute()
        log_event("signup", email)
    return True, email

def track_line():
    """Public accuracy line. Counts every checked prediction the app made, including the owner's."""
    rows = sb.table("predictions").select("outcome,correct,created").execute().data
    checked = [r for r in rows if r.get("outcome") is not None]
    n = len(checked)
    c = sum(int(r.get("correct") or 0) for r in checked)
    if n == 0:
        return ("All predictions made by Matchday Prediction: none have been checked yet. "
                "Results appear here once matches are played.")
    since = min(r["created"] for r in rows)[:10] if rows else "-"
    if n < 10:
        return (f"All predictions made by Matchday Prediction: {c} of {n} checked predictions had the "
                f"most likely outcome correct so far (since {since}). That is too few to judge.")
    return (f"All predictions made by Matchday Prediction: most likely outcome correct in {c} of {n} "
            f"checked predictions ({c/n:.0%}), since {since}. Estimates, not guarantees.")

def prediction_stats(email=None):
    """Counts of predictions, checked results, correct and wrong. Pass an email for one person's record."""
    q = sb.table("predictions").select("outcome,correct,created")
    if email:
        q = q.eq("email", email)
    rows = q.execute().data
    played = [r for r in rows if r.get("outcome") is not None]
    correct = sum(1 for r in played if r.get("correct"))
    since = min((r["created"] for r in rows), default=None)
    return {
        "total": len(rows),
        "played": len(played),
        "correct": correct,
        "wrong": len(played) - correct,
        "pending": len(rows) - len(played),
        "since": since[:10] if since else None,
    }

def stats_card(s, title):
    """A record card: totals, correct and wrong with percentages, and how many are still pending."""
    if s["total"] == 0:
        return f'<div class="pbox"><div class="pbox-title">{title}</div>No predictions yet.</div>'
    p = s["played"]
    correct_pct = f"{s['correct'] / p * 100:.1f}%" if p else "-"
    wrong_pct = f"{s['wrong'] / p * 100:.1f}%" if p else "-"
    since_line = f"<div>Since: <b>{s['since']}</b></div>" if s["since"] else ""
    early = ("" if p >= 30 else
             '<div style="font-size:0.78rem;color:#64748B;margin-top:6px">'
             'Early figures: fewer than 30 checked predictions, so the percentages will still move.</div>')
    body = (
        f"<div>Total predictions made: <b>{s['total']}</b></div>"
        f"<div>Checked against results: <b>{p}</b></div>"
        f"<div>Correct (most likely outcome): <b>{s['correct']} of {p} ({correct_pct})</b></div>"
        f"<div>Wrong: <b>{s['wrong']} of {p} ({wrong_pct})</b></div>"
        f"<div>Awaiting result: <b>{s['pending']}</b></div>"
        f"{since_line}"
    )
    return f'<div class="pbox"><div class="pbox-title">{title}</div>{body}{early}</div>'

# Log one visit per browser session (not on every rerun)
if not st.session_state.visit_logged:
    log_event("visit")
    st.session_state.visit_logged = True

# ----- Conversations -----
def create_conversation(email):
    res = sb.table("conversations").insert({
        "email": email, "title": NEW_CHAT_TITLE, "created": now_iso(),
    }).execute()
    return res.data[0]["id"]

def list_conversations(email):
    res = (sb.table("conversations").select("id,title").eq("email", email)
           .order("id", desc=True).limit(30).execute())
    return [(r["id"], r["title"]) for r in res.data]

def load_conv_messages(conv_id):
    res = (sb.table("chat_messages").select("role,text").eq("conv_id", conv_id)
           .order("id").execute())
    return [{"role": r["role"], "text": r["text"]} for r in res.data]

def add_message(role, text):
    st.session_state.messages.append({"role": role, "text": text})
    email = st.session_state.user_email
    conv_id = st.session_state.conv_id
    if email and conv_id:
        sb.table("chat_messages").insert({
            "conv_id": conv_id, "email": email, "role": role,
            "text": text, "created": now_iso(),
        }).execute()
        if role == "user":
            # Name the chat after its first question
            sb.table("conversations").update({"title": text[:40]}) \
                .eq("id", conv_id).eq("title", NEW_CHAT_TITLE).execute()

def go_home():
    """Show the start screen. The chat stays saved in Previous chats."""
    st.session_state.messages = []
    st.session_state.paywall = False
    st.session_state.pop("chat", None)
    st.session_state.conv_id = None
    save_progress(conv_id=None)

def start_new_chat():
    st.session_state.conv_id = create_conversation(st.session_state.user_email)
    st.session_state.messages = []
    st.session_state.paywall = False
    st.session_state.pop("chat", None)
    save_progress(conv_id=st.session_state.conv_id)

def open_chat(conv_id):
    st.session_state.conv_id = conv_id
    st.session_state.messages = load_conv_messages(conv_id)
    st.session_state.paywall = False
    st.session_state.pop("chat", None)
    save_progress(conv_id=conv_id)

def delete_all_chats():
    email = st.session_state.user_email
    sb.table("chat_messages").delete().eq("email", email).execute()
    sb.table("conversations").delete().eq("email", email).execute()
    start_new_chat()

# ----- Session persistence (survives browser refresh) -----
def ensure_token():
    """Create a session row once per browser visit and keep its token in the page link."""
    tok = st.session_state.get("token")
    if not tok:
        tok = secrets.token_urlsafe(24)
        sb.table("sessions").insert({
            "token": tok,
            "email": st.session_state.get("user_email"),
            "terms_ok": True,
            "age_ok": True,
            "conv_id": st.session_state.get("conv_id"),
            "created": now_iso(),
        }).execute()
        st.session_state.token = tok
        st.query_params["s"] = tok
    return tok

def save_progress(**fields):
    """Save progress (email, chat) so a refresh brings the user back to the same place."""
    tok = ensure_token()
    sb.table("sessions").update(fields).eq("token", tok).execute()

def end_session():
    tok = st.session_state.get("token")
    if tok:
        sb.table("sessions").delete().eq("token", tok).execute()
    st.session_state.token = None
    if "s" in st.query_params:
        del st.query_params["s"]

# Restore a previous visit from the page link, once per browser load
if not st.session_state.restored:
    st.session_state.restored = True
    tok = st.query_params.get("s")
    if tok:
        rows = sb.table("sessions").select("*").eq("token", tok).execute().data
        if rows:
            row = rows[0]
            st.session_state.token = tok
            st.session_state.user_email = row["email"]
            urow = sb.table("users").select("username").eq("email", row["email"]).execute().data
            saved_name = urow[0].get("username") if urow else None
            st.session_state.user_name = saved_name or (row["email"] or "").split("@")[0]
            st.session_state.conv_id = row["conv_id"]
            if row["conv_id"]:
                st.session_state.messages = load_conv_messages(row["conv_id"])

# ----- Credits and account ledger -----
def get_credits(email):
    res = sb.table("wallet").select("credits").eq("email", email).execute()
    return res.data[0]["credits"] if res.data else 0

def ledger_add(email, kind, credits, note=""):
    """Record one movement in the account history. Positive adds credits, negative spends them."""
    sb.table("ledger").insert({
        "email": email, "kind": kind, "credits": credits,
        "note": note, "created": now_iso(),
    }).execute()

def account_view(email):
    credits = get_credits(email)
    history = (sb.table("ledger").select("kind,credits,note,created")
               .eq("email", email).order("id", desc=True).limit(15).execute().data)
    return credits, history

def spend_credit(email):
    c = get_credits(email)
    if c > 0:
        sb.table("wallet").update({"credits": c - 1}).eq("email", email).execute()
        ledger_add(email, "prediction", -1, "Prediction")

def get_my_ref_code(email):
    """Returns the user's referral code, creating one if the account has none yet."""
    res = sb.table("users").select("ref_code").eq("email", email).execute().data
    code = res[0]["ref_code"] if res else None
    if not code:
        code = secrets.token_hex(4).upper()
        sb.table("users").update({"ref_code": code}).eq("email", email).execute()
    return code

def reward_referrer(email):
    """Called after a referred friend's first credited pack. Rewards only once."""
    rows = (sb.table("referrals").select("referrer")
            .eq("referee", email).eq("rewarded", False).execute().data)
    if not rows:
        return
    referrer = rows[0]["referrer"]
    sb.table("referrals").update({"rewarded": True}).eq("referee", email).execute()
    sb.table("wallet").upsert({
        "email": referrer,
        "credits": get_credits(referrer) + REFERRAL_CREDITS,
    }).execute()
    ledger_add(referrer, "referral", REFERRAL_CREDITS, "Friend's first pack")

def redeem_code(email, code):
    code = (code or "").strip()
    if code not in CODES:
        return False, "That code is not valid. Check it and try again."
    if sb.table("redemptions").select("code").eq("code", code).execute().data:
        return False, "That code has already been used."
    try:
        # The primary key on code makes this insert fail if two people redeem at once
        sb.table("redemptions").insert({"code": code, "email": email, "created": now_iso()}).execute()
    except Exception:
        return False, "That code has already been used."
    sb.table("wallet").upsert({"email": email, "credits": get_credits(email) + PACK_SIZE}).execute()
    ledger_add(email, "top_up", PACK_SIZE, "Access code pack")
    reward_referrer(email)
    return True, f"{PACK_SIZE} prediction credits added (KSh {PACK_SIZE * CREDIT_KSH})."

def owner_credit(buyer, ref, packs):
    """Owner adds credits after checking a PayBill payment. Each confirmation code works once."""
    buyer = (buyer or "").strip().lower()
    ref = (ref or "").strip().upper()
    if "@" not in buyer or not ref:
        return False, "Enter the buyer's email and the M-Pesa confirmation code."
    marker = f"MPESA:{ref}"
    if sb.table("redemptions").select("code").eq("code", marker).execute().data:
        return False, f"Code {ref} has already been credited."
    sb.table("redemptions").insert({"code": marker, "email": buyer, "created": now_iso()}).execute()
    sb.table("wallet").upsert({"email": buyer, "credits": get_credits(buyer) + packs * PACK_SIZE}).execute()
    ledger_add(buyer, "top_up", packs * PACK_SIZE, f"PayBill {ref}")
    reward_referrer(buyer)
    return True, f"Added {packs * PACK_SIZE} credits to {buyer}."

CODES = [c.strip() for c in get_secret("ACCESS_CODES").split(",") if c.strip()]
PAY_PRICE = get_secret("PAY_PRICE", "100")
PAYBILL_NUMBER = get_secret("PAYBILL_NUMBER", "not set")
ACCOUNT_NUMBER = get_secret("ACCOUNT_NUMBER", "not set")

# ---------- Step 1: sign in with email and username ----------
if not st.session_state.user_email:
    st.markdown("### Sign in")
    st.caption("Enter your email and a username to continue.")
    with st.form("signin"):
        email_in = st.text_input("Email")
        name_in = st.text_input("Username")
        submitted = st.form_submit_button("Continue")
    if submitted:
        if not name_in.strip():
            st.error("Please enter a username.")
        else:
            ok, result = sign_in(email_in, name_in.strip())
            if ok:
                st.session_state.user_email = result
                st.session_state.user_name = name_in.strip()
                log_event("signin", result)
                # Every sign-in starts a fresh chat; older chats stay in the sidebar
                st.session_state.conv_id = create_conversation(result)
                st.session_state.messages = []
                st.session_state.paywall = False
                st.session_state.pop("chat", None)
                save_progress(email=result, conv_id=st.session_state.conv_id)
                st.rerun()
            else:
                st.error(result)
    st.stop()

# ---------- Sidebar: account, chats, balance ----------
st.sidebar.markdown(
    f"**Signed in as**  \n{st.session_state.user_name}  \n{st.session_state.user_email}"
)

if is_owner(st.session_state.user_email):
    st.sidebar.markdown("**Account balance:** unlimited (owner)")
else:
    credits, history = account_view(st.session_state.user_email)
    st.sidebar.markdown(
        f"**Account balance:** KSh {credits * CREDIT_KSH}  \n"
        f"{credits} prediction credits at KSh {CREDIT_KSH} each"
    )
    with st.sidebar.expander("🧾 Account history"):
        for h in history:
            sign = "+" if h["credits"] > 0 else ""
            when = h["created"][:16].replace("T", " ")
            st.write(f"{when}  \n{h['note']}: {sign}{h['credits']} credit(s)")
        if not history:
            st.caption("No activity yet.")

st.sidebar.button("🏠 Home", on_click=go_home, use_container_width=True)
st.sidebar.button("➕ New chat", on_click=start_new_chat, use_container_width=True)

st.sidebar.markdown("**Previous chats**")
for conv_id, title in list_conversations(st.session_state.user_email):
    marker = "▶ " if conv_id == st.session_state.conv_id else ""
    st.sidebar.button(
        f"{marker}{title}",
        key=f"conv_{conv_id}",
        on_click=open_chat,
        args=(conv_id,),
        use_container_width=True,
    )

if st.sidebar.button("🗑️ Delete all my chats"):
    delete_all_chats()
    st.rerun()

if st.sidebar.button("Sign out"):
    end_session()
    st.session_state.user_email = None
    st.session_state.user_name = None
    st.session_state.conv_id = None
    st.session_state.messages = []
    st.session_state.paywall = False
    st.session_state.pop("chat", None)
    st.rerun()

st.sidebar.markdown(stats_card(prediction_stats(), "All predictions"), unsafe_allow_html=True)
st.sidebar.markdown(stats_card(prediction_stats(st.session_state.user_email), "My record"),
                    unsafe_allow_html=True)

my_code = get_my_ref_code(st.session_state.user_email)
st.sidebar.markdown(f"**Your referral code:** `{my_code}`")
st.sidebar.caption(
    f"Share it. You get {REFERRAL_CREDITS} free credit when a friend who signed up "
    f"with it buys their first pack."
)
st.sidebar.caption("Credits stay on your account when you delete chats.")

# ---------- About (business identity, for transparency) ----------
with st.sidebar.expander("ℹ️ About this app"):
    st.markdown(f"""
**{APP_NAME}** is an information and analysis tool for football fans.

- **Operator:** Matchday analysis
- **Registration:** BN/2026/123123
- **Contact:** +254 797 652122
- **Address:** Miharati, Nyandarua, Kenya

**Data source:** fixtures, tables and results come from football-data.org. Data can be delayed or incomplete.

**Accuracy:** predictions are estimates, not guarantees. Track-record figures appear only after enough predictions are checked, and they are early until then.

**Refunds:** Prediction credits are non-refundable once purchased, as stated in the terms. This does not affect any rights you have under Kenyan consumer law.
""")

st.markdown('<p class="disclaimer">Probabilities are estimates for discussion, not guarantees or betting advice.</p>',
            unsafe_allow_html=True)

# ---------- Sound and voice helpers ----------
def pcm_to_wav(pcm, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()

@st.cache_data
def make_chime(notes, rate=24000):
    frames = bytearray()
    for freq, dur in notes:
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / (0.01 * rate), (n - i) / (0.03 * rate))
            sample = 0.3 * env * math.sin(2 * math.pi * freq * i / rate)
            frames += struct.pack("<h", int(sample * 32767))
    return pcm_to_wav(bytes(frames), rate)

SEND_SOUND = make_chime(((880, 0.10), (1320, 0.12)))

key = get_secret("GEMINI_API_KEY")
if not key:
    st.error("The app is not set up yet (API key missing).")
    st.stop()

FOOTBALL_KEY = get_secret("FOOTBALL_API_KEY").strip()

@st.cache_resource
def get_client():
    return genai.Client(api_key=key)

client = get_client()

# ---------- Football data (cached to respect rate limits) ----------
@st.cache_data(ttl=900)
def league_fixtures(code, _key):
    if not _key:
        return None, "No football key found in secrets."
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{code}/matches",
            headers={"X-Auth-Token": _key},
            params={"status": "SCHEDULED"},
            timeout=10,
        )
        if r.status_code != 200:
            return None, f"status {r.status_code}"
        return r.json().get("matches", []), None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600)
def league_table(code, _key):
    if not _key:
        return None, "No football key found in secrets."
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{code}/standings",
            headers={"X-Auth-Token": _key},
            timeout=10,
        )
        if r.status_code != 200:
            return None, f"status {r.status_code}"
        standings = r.json().get("standings", [])
        table = standings[0].get("table", []) if standings else None
        return table, None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600)
def team_finished(team_id, _key, n=20):
    """Finished matches for one team, newest first. Cached for an hour."""
    if not _key:
        return None
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/teams/{team_id}/matches",
            headers={"X-Auth-Token": _key},
            params={"status": "FINISHED", "limit": n},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return r.json().get("matches", [])
    except Exception:
        return None

@st.cache_data(ttl=3600)
def team_scheduled(team_id, _key):
    """Next scheduled matches for one team. Cached for an hour."""
    if not _key:
        return None
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/teams/{team_id}/matches",
            headers={"X-Auth-Token": _key},
            params={"status": "SCHEDULED", "limit": 3},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return r.json().get("matches", [])
    except Exception:
        return None

@st.cache_data(ttl=3600)
def finished_matches(code, _key):
    """Finished matches for one league. Cached for an hour."""
    if not _key:
        return []
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{code}/matches",
            headers={"X-Auth-Token": _key},
            params={"status": "FINISHED"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return r.json().get("matches", [])
    except Exception:
        return []

def fmt_kickoff(utc_str):
    """Turn football-data's UTC time into Nairobi time, e.g. 'Sat 18 Oct, 17:30'."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00")).astimezone(EAT)
    return dt.strftime("%a %d %b, %H:%M")

def days_between(utc_str):
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days

def table_intent(text):
    t = text.lower()
    if any(w in t for w in ["table", "standings", "league position"]):
        return "table"
    if any(w in t for w in ["fixture", "upcoming", "schedule", "next match", "next games"]):
        return "fixtures"
    return None

def dtable(headers, rows):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(rows)
    return (f'<div class="dtable-wrap"><table class="dtable">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

def fixtures_html(code):
    matches, err = league_fixtures(code, FOOTBALL_KEY)
    if not matches:
        return f"<p>Fixtures are unavailable right now ({html.escape(str(err or 'no matches'))}).</p>"
    rows = []
    for m in matches[:20]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(m.get('matchday') or '-'))}</td>"
            f"<td>{fmt_kickoff(m['utcDate'])}</td>"
            f"<td class='name'>{html.escape(m['homeTeam']['name'])}</td>"
            "<td>vs</td>"
            f"<td class='name'>{html.escape(m['awayTeam']['name'])}</td>"
            "</tr>"
        )
    return dtable(["Matchday", "Kickoff (Nairobi)", "Home", "", "Away"], rows)

def standings_html(code):
    table, err = league_table(code, FOOTBALL_KEY)
    if not table:
        return f"<p>The table is unavailable right now ({html.escape(str(err or 'no table'))}).</p>"
    rows = []
    for r in table:
        gd = r.get("goalDifference", 0)
        gd_txt = f"+{gd}" if gd > 0 else str(gd)
        form = r.get("form") or "-"
        form = " ".join(x for x in form.split(",") if x) if form != "-" else "-"
        rows.append(
            "<tr>"
            f"<td>{r['position']}</td>"
            f"<td class='name'>{html.escape(r['team']['name'])}</td>"
            f"<td>{r['playedGames']}</td>"
            f"<td>{r['won']}</td>"
            f"<td>{r['draw']}</td>"
            f"<td>{r['lost']}</td>"
            f"<td>{r['goalsFor']}</td>"
            f"<td>{r['goalsAgainst']}</td>"
            f"<td>{gd_txt}</td>"
            f"<td><b>{r['points']}</b></td>"
            f"<td>{html.escape(form)}</td>"
            "</tr>"
        )
    return dtable(["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts", "Form"], rows)

def results_html(codes, limit=30):
    rows = []
    for code in codes:
        for m in finished_matches(code, FOOTBALL_KEY):
            ft = (m.get("score") or {}).get("fullTime") or {}
            if ft.get("home") is None or ft.get("away") is None:
                continue
            rows.append((m["utcDate"], m["homeTeam"]["name"], ft["home"], ft["away"], m["awayTeam"]["name"]))
    rows.sort(reverse=True)
    if not rows:
        return "<p>No finished results to show yet.</p>"
    body = [
        "<tr>"
        f"<td>{fmt_kickoff(d)}</td>"
        f"<td class='name'>{html.escape(h)}</td>"
        f"<td><b>{hs} - {as_}</b></td>"
        f"<td class='name'>{html.escape(a)}</td>"
        "</tr>"
        for d, h, hs, as_, a in rows[:limit]
    ]
    return dtable(["Date (Nairobi)", "Home", "Score", "Away"], body)

def fixtures_context(code, limit=10):
    matches, err = league_fixtures(code, FOOTBALL_KEY)
    if not matches:
        return f"Live fixture data is unavailable right now ({err or 'no matches returned'})."
    lines = []
    for m in matches[:limit]:
        date = m["utcDate"][:16].replace("T", " ")
        lines.append(f"{date} UTC: {m['homeTeam']['name']} vs {m['awayTeam']['name']}")
    return "Upcoming fixtures:\n" + "\n".join(lines)

def table_context(code, limit=20):
    table, err = league_table(code, FOOTBALL_KEY)
    if not table:
        return f"League table is unavailable right now ({err or 'no table returned'})."
    lines = []
    for row in table[:limit]:
        lines.append(
            f"{row['position']}. {row['team']['name']} (id {row['team']['id']}): "
            f"P{row['playedGames']} W{row['won']} D{row['draw']} L{row['lost']} "
            f"GF{row['goalsFor']} GA{row['goalsAgainst']} Pts{row['points']}"
        )
    return "Current table:\n" + "\n".join(lines)

def team_profile(team_id, team_name, league_code):
    """Structured context for one team: form, home/away splits, rest, next fixture.
    Only lines the football data provides are included."""
    lines = [f"{team_name}:"]

    games = team_finished(team_id, FOOTBALL_KEY) or []
    scored_games = []
    for g in games:
        ft = (g.get("score") or {}).get("fullTime") or {}
        if ft.get("home") is None or ft.get("away") is None:
            continue
        if g.get("competition", {}).get("code") != league_code and league_code != "CL":
            continue
        scored_games.append(g)
    scored_games = scored_games[:RECENT_N]

    if scored_games:
        pts = 0
        gf = ga = 0
        h_gf = h_ga = h_n = a_gf = a_ga = a_n = 0
        results = []
        for g in scored_games:
            ft = g["score"]["fullTime"]
            is_home = g["homeTeam"]["id"] == team_id
            mine = ft["home"] if is_home else ft["away"]
            theirs = ft["away"] if is_home else ft["home"]
            opp = g["awayTeam"]["name"] if is_home else g["homeTeam"]["name"]
            if mine > theirs:
                res, pts = "W", pts + 3
            elif mine < theirs:
                res = "L"
            else:
                res, pts = "D", pts + 1
            gf += mine
            ga += theirs
            if is_home:
                h_gf += mine; h_ga += theirs; h_n += 1
            else:
                a_gf += mine; a_ga += theirs; a_n += 1
            results.append(f"{res} {mine}-{theirs} vs {opp} ({'H' if is_home else 'A'})")
        n = len(scored_games)
        lines.append(f"  Last {n} league/CL matches: {pts} pts, "
                     f"scored {gf/n:.2f}/game, conceded {ga/n:.2f}/game")
        if h_n:
            lines.append(f"  Home ({h_n}): scored {h_gf/h_n:.2f}, conceded {h_ga/h_n:.2f} per game")
        if a_n:
            lines.append(f"  Away ({a_n}): scored {a_gf/a_n:.2f}, conceded {a_ga/a_n:.2f} per game")
        lines.append("  Results (newest first): " + "; ".join(results))
        last_date = scored_games[0].get("utcDate")
        if last_date:
            lines.append(f"  Days since last match: {days_between(last_date)}")

    nxt = team_scheduled(team_id, FOOTBALL_KEY) or []
    if nxt:
        m = nxt[0]
        venue = "home" if m["homeTeam"]["id"] == team_id else "away"
        opp = m["awayTeam"]["name"] if venue == "home" else m["homeTeam"]["name"]
        lines.append(f"  Next match: {fmt_kickoff(m['utcDate'])} EAT, {venue} vs {opp}")
    return "\n".join(lines)

def head_to_head(home_id, away_id, home_name, away_name):
    games = team_finished(home_id, FOOTBALL_KEY) or []
    meet = []
    for g in games:
        ids = {g["homeTeam"]["id"], g["awayTeam"]["id"]}
        ft = (g.get("score") or {}).get("fullTime") or {}
        if away_id in ids and ft.get("home") is not None:
            meet.append(
                f"{g['homeTeam']['name']} {ft['home']}-{ft['away']} {g['awayTeam']['name']} "
                f"({g.get('utcDate', '')[:10]})"
            )
    meet = meet[:H2H_N]
    if not meet:
        return ""
    return f"Head-to-head ({home_name} vs {away_name}), most recent first:\n  " + "\n  ".join(meet)

def match_context(code):
    return fixtures_context(code) + "\n\n" + table_context(code)

def prediction_context(code, home_name, away_name):
    """Full context for a named match: both team profiles plus head-to-head."""
    table, _ = league_table(code, FOOTBALL_KEY)
    if not table:
        return "League table unavailable, so team data cannot be built."
    by_name = {}
    for row in table:
        by_name[row["team"]["name"].lower()] = row["team"]
    h = next((t for n, t in by_name.items() if home_name.lower() in n), None)
    a = next((t for n, t in by_name.items() if away_name.lower() in n), None)
    if not h or not a:
        return "Could not match both teams in this league's table."
    parts = [
        team_profile(h["id"], h["name"], code),
        team_profile(a["id"], a["name"], code),
        head_to_head(h["id"], a["id"], h["name"], a["name"]),
    ]
    return "\n\n".join(p for p in parts if p)

def find_team_rows(code, text):
    """Return (home, away) team dicts in the order named in the question."""
    table, _ = league_table(code, FOOTBALL_KEY)
    if not table:
        return None
    t = text.lower()
    hits = []
    for row in table:
        for name in (row["team"]["name"], row["team"].get("shortName") or ""):
            i = t.find(name.lower()) if name else -1
            if i >= 0:
                hits.append((i, row["team"]))
                break
    hits.sort(key=lambda x: x[0])
    if len(hits) >= 2:
        return hits[0][1], hits[1][1]
    return None

def log_prediction(email, code, home, away, probs):
    sb.table("predictions").insert({
        "email": email, "league": code,
        "home_id": home["id"], "away_id": away["id"],
        "home": home["name"], "away": away["name"],
        "p_home": probs[0], "p_draw": probs[1], "p_away": probs[2],
        "created": now_iso(),
    }).execute()

def resolve_predictions():
    rows = (sb.table("predictions")
            .select("id,home_id,away_id,p_home,p_draw,p_away,created")
            .is_("outcome", "null").execute().data)
    for r in rows:
        pid, hid, aid = r["id"], r["home_id"], r["away_id"]
        ph, pd_, pa = r["p_home"], r["p_draw"], r["p_away"]
        made = datetime.fromisoformat(r["created"])
        if made.tzinfo is None:
            made = made.replace(tzinfo=timezone.utc)
        for g in team_finished(hid, FOOTBALL_KEY) or []:
            ids = {g["homeTeam"]["id"], g["awayTeam"]["id"]}
            ft = (g.get("score") or {}).get("fullTime") or {}
            if aid not in ids or ft.get("home") is None:
                continue
            played = datetime.fromisoformat(g["utcDate"].replace("Z", "+00:00"))
            if played < made:
                continue
            if g["homeTeam"]["id"] == hid:
                hg, ag = ft["home"], ft["away"]
            else:
                hg, ag = ft["away"], ft["home"]
            outcome = "H" if hg > ag else ("A" if ag > hg else "D")
            predicted = max([("H", ph), ("D", pd_), ("A", pa)], key=lambda x: x[1])[0]
            sb.table("predictions").update({
                "outcome": outcome, "correct": int(predicted == outcome),
            }).eq("id", pid).execute()
            break

# Check predictions against finished results once per session
if not st.session_state.resolved:
    resolve_predictions()
    st.session_state.resolved = True

# ---------- Chat setup ----------
SYSTEM_PROMPT = (
    "You are Matchday Prediction, a football match analyst for fans of top European leagues. "
    "Use only the data provided in each message. Quote the figures you rely on. "
    "Never mention missing, unavailable or unknown data, and never say what you do not know. "
    "Simply leave out anything the data does not cover, and talk only about what is there. "
    "Never assume any player is fit or injured. "
    "When model figures are provided, use exactly the percentages given and do not change them. "
    "Give three short reasons that cite the figures. Never present a prediction as "
    "certain, never give betting tips, and never encourage betting. If asked about betting, "
    "briefly explain that you analyse matches but do not advise on bets. If the user attaches "
    "a screenshot or PDF, read it carefully and use it. Keep replies concise and clear."
)

def gemini_history(msgs):
    out = []
    for m in msgs[-HISTORY_LIMIT:]:
        if m["role"] not in ("user", "assistant"):
            continue  # table and card rows are display-only, never sent to the model
        role = "user" if m["role"] == "user" else "model"
        out.append(types.Content(role=role, parts=[types.Part(text=m["text"])]))
    return out

def new_chat(history):
    return client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        history=history,
    )

if "chat" not in st.session_state:
    st.session_state.chat = new_chat(gemini_history(st.session_state.messages))

def current_attachment():
    return st.session_state.get(f"att_{st.session_state.att_n}")

def submit_draft():
    text = st.session_state.get("draft", "").strip()
    att = current_attachment()
    if text or att is not None:
        st.session_state.to_send = text or "Please analyse this file."
    st.session_state.draft = ""

def pick_quick(question):
    st.session_state.to_send = question

def needs_credit(text_in):
    """Decide with keywords only, so each question uses one model call at most.
    The percentage check in ask() still catches predictions that slip through."""
    t = text_in.lower()
    if any(w in t for w in GENERAL_KEYWORDS):
        return False
    if any(w in t for w in PAID_KEYWORDS):
        return True
    return False

def speak(text):
    try:
        r = client.models.generate_content(
            model=TTS_MODEL,
            contents=text[:1500],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
                    )
                ),
            ),
        )
        pcm = r.candidates[0].content.parts[0].inline_data.data
        return pcm_to_wav(pcm, 24000)
    except Exception:
        return None

def team_card(team_id, team_name, league_code):
    """One team's stats as a card. Lines the data does not provide are left out."""
    games = team_finished(team_id, FOOTBALL_KEY) or []
    scored = []
    for g in games:
        ft = (g.get("score") or {}).get("fullTime") or {}
        if ft.get("home") is None or ft.get("away") is None:
            continue
        if g.get("competition", {}).get("code") != league_code and league_code != "CL":
            continue
        scored.append(g)
    scored = scored[:RECENT_N]

    results, gf, ga = [], 0, 0
    hw = hd = hl = aw = ad = al = 0
    for g in scored:
        ft = g["score"]["fullTime"]
        is_home = g["homeTeam"]["id"] == team_id
        mine = ft["home"] if is_home else ft["away"]
        theirs = ft["away"] if is_home else ft["home"]
        gf += mine
        ga += theirs
        if mine > theirs:
            res = "W"
            if is_home: hw += 1
            else: aw += 1
        elif mine < theirs:
            res = "L"
            if is_home: hl += 1
            else: al += 1
        else:
            res = "D"
            if is_home: hd += 1
            else: ad += 1
        results.append(res)

    n = len(scored)
    parts = []
    if n:
        pts = sum(3 if r == "W" else 1 if r == "D" else 0 for r in results)
        form_html = "".join(
            f'<span class="{ {"W": "f-w", "D": "f-d", "L": "f-l"}[r] }">{r}</span>'
            for r in results[:5]
        )
        parts.append(
            f'<div class="tcard-grid">'
            f'<div>Last {n}: <b>{pts} pts</b></div>'
            f'<div>Goals: <b>{gf/n:.2f} for, {ga/n:.2f} against</b> per game</div>'
            f'<div>Home: <b>{hw}W {hd}D {hl}L</b></div>'
            f'<div>Away: <b>{aw}W {ad}D {al}L</b></div>'
            f'<div>Last match: <b>{days_between(scored[0]["utcDate"])} days ago</b></div>'
            f'</div>'
            f'<div class="tcard-form">Recent form: {form_html}</div>'
        )

    nxt = team_scheduled(team_id, FOOTBALL_KEY) or []
    badge = ""
    if nxt:
        m = nxt[0]
        venue = "home" if m["homeTeam"]["id"] == team_id else "away"
        opp = m["awayTeam"]["name"] if venue == "home" else m["homeTeam"]["name"]
        badge = (f'<span class="tcard-badge">Next: {fmt_kickoff(m["utcDate"])} '
                 f'({venue} vs {html.escape(opp)})</span>')

    head = (f'<div class="tcard-head"><span class="tcard-name">{html.escape(team_name)}</span>'
            f'{badge}</div>')
    return f'<div class="tcard">{head}{"".join(parts)}</div>'

# Common Swahili words. Two or more in a message switch the reply to Swahili.
SW_WORDS = {
    "habari", "mechi", "nani", "je", "ni", "naomba", "nataka", "unaweza", "sasa",
    "leo", "kesho", "karibu", "timu", "utabiri", "msimamo", "ratiba", "kwa", "na",
    "wapi", "gani", "vipi", "ipi", "asante", "tafadhali",
}

def detect_lang(text):
    """Return 'sw' if the message has at least two common Swahili words, otherwise 'en'."""
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    return "sw" if len(words & SW_WORDS) >= 2 else "en"

LABELS = {
    "en": {"chances": "Estimated chances", "draw": "Draw", "reply_in": "English",
           "paywall": ("Predictions and probability estimates use prediction credits, and you have none left. "
                       "Pay below to add more. General questions about fixtures, form, "
                       "and the table are still free."),
           "was_prediction": "That was a prediction, which uses prediction credits. Pay below to add more.",
           "failed": "I couldn't get an analysis just now. Please try again or rephrase your question.",
           "correct": "✔ Correct predictions", "wrong": "✘ Wrong predictions",
           "pending": "⏳ Awaiting result", "summary": "Summary"},
    "sw": {"chances": "Uwezekano unaokadiriwa", "draw": "Sare", "reply_in": "Swahili",
           "paywall": ("Utabiri na makadirio ya uwezekano hutumia salio la utabiri, nawe huna salio. "
                       "Lipa hapa chini ili kuongeza. Maswali ya ratiba, msimamo na fomu bado ni bure."),
           "was_prediction": "Hilo lilikuwa utabiri, unaotumia salio la utabiri. Lipa hapa chini ili kuongeza.",
           "failed": "Sikuweza kupata uchambuzi sasa hivi. Tafadhali jaribu tena au uulize kwa njia nyingine.",
           "correct": "✔ Utabiri sahihi", "wrong": "✘ Utabiri usio sahihi",
           "pending": "⏳ Inasubiri matokeo", "summary": "Muhtasari"},
}

NO_HISTORY = {
    "en": "There is not enough finished match history for these two teams in this league yet, so no prediction was made and no credit was used.",
    "sw": "Hakuna historia ya kutosha ya mechi kwa timu hizi mbili kwenye ligi hii bado, kwa hiyo hakuna utabiri na salio halijatumika.",
}

RESULT_WORDS = ["result", "score", "outcome", "finished", "full time",
                "accuracy", "record", "percentage", "how many"]
MINE_WORDS = [
    "my prediction", "my predictions", "predictions were", "predicted", "i predicted",
    "today's predictions", "todays predictions", "past predictions", "previous predictions",
    "my picks",
]

def results_intent(text):
    t = text.lower()
    return any(w in t for w in RESULT_WORDS + MINE_WORDS)

def is_mine_intent(text):
    t = text.lower()
    return any(w in t for w in MINE_WORDS)

def my_predictions_html(email, today_only=False):
    L = LABELS[st.session_state.get("lang", "en")]
    rows = (sb.table("predictions")
            .select("home,away,p_home,p_draw,p_away,outcome,correct,created")
            .eq("email", email).order("id", desc=True).limit(50).execute().data)
    if today_only:
        today = datetime.now(EAT).date()
        rows = [r for r in rows
                if datetime.fromisoformat(r["created"]).astimezone(EAT).date() == today]
    if not rows:
        return "<p>No predictions to show for this period.</p>"

    def cells(r):
        probs = {"H": r["p_home"], "D": r["p_draw"], "A": r["p_away"]}
        names = {"H": r["home"], "D": L["draw"], "A": r["away"]}
        pick = max(probs, key=probs.get)
        when = datetime.fromisoformat(r["created"]).astimezone(EAT).strftime("%d %b")
        res = "-" if r["outcome"] is None else names[r["outcome"]]
        return (
            f"<td>{when}</td>"
            f"<td class='name'>{html.escape(r['home'])} vs {html.escape(r['away'])}</td>"
            f"<td>{html.escape(names[pick])} ({probs[pick]:.0f}%)</td>"
            f"<td>{html.escape(res)}</td>"
        )

    correct = [r for r in rows if r["outcome"] is not None and r["correct"]]
    wrong = [r for r in rows if r["outcome"] is not None and not r["correct"]]
    pending = [r for r in rows if r["outcome"] is None]
    played = len(correct) + len(wrong)
    cpct = f"{len(correct) / played * 100:.1f}%" if played else "-"
    wpct = f"{len(wrong) / played * 100:.1f}%" if played else "-"

    out = (
        f'<div class="pbox"><div class="pbox-title">{L["summary"]}</div>'
        f"<div>Checked: <b>{played}</b></div>"
        f"<div>Correct: <b>{len(correct)} of {played} ({cpct})</b></div>"
        f"<div>Wrong: <b>{len(wrong)} of {played} ({wpct})</b></div>"
        f"<div>Awaiting result: <b>{len(pending)}</b></div>"
        "</div>"
    )
    headers = ["Made", "Match", "Most likely", "Result"]
    if correct:
        out += f'<div class="quick-title">{L["correct"]}</div>'
        out += dtable(headers, [f"<tr>{cells(r)}</tr>" for r in correct])
    if wrong:
        out += f'<div class="quick-title">{L["wrong"]}</div>'
        out += dtable(headers, [f"<tr>{cells(r)}</tr>" for r in wrong])
    if pending:
        out += f'<div class="quick-title">{L["pending"]}</div>'
        out += dtable(headers, [f"<tr>{cells(r)}</tr>" for r in pending])
    return out

def results_block(text_in, email, league_code):
    """Answer a results, record, or my-predictions question. Free: no model call, no credit."""
    t = text_in.lower()
    if any(w in t for w in ["accuracy", "record", "percentage", "how many"]):
        return (stats_card(prediction_stats(email), "My record")
                + stats_card(prediction_stats(), "All predictions"))
    if is_mine_intent(text_in):
        return my_predictions_html(email, today_only="today" in t)
    if "all" in t or "every" in t:
        codes = list(LEAGUES.values())
    else:
        codes = [league_code]
    return results_html(codes)

def prob_bars(home, away, probs):
    """The estimated chances at the bottom of a prediction, in the current language."""
    L = LABELS[st.session_state.get("lang", "en")]
    rows = [(home, probs[0]), (L["draw"], probs[1]), (away, probs[2])]
    body = "".join(
        f'<div class="pbar-row"><span>{html.escape(label)}</span>'
        f'<div class="pbar"><div class="pfill" style="width:{p:.0f}%"></div></div>'
        f'<b>{p:.0f}%</b></div>'
        for label, p in rows
    )
    return f'<div class="pbox"><div class="pbox-title">{L["chances"]}</div>{body}</div>'

def model_figures(code, home, away):
    """Elo and Poisson figures for a match, from the league's finished matches."""
    matches = sorted(finished_matches(code, FOOTBALL_KEY), key=lambda m: m["utcDate"])
    return model_predict(matches, home["id"], away["id"])

def figures_block(f):
    """The model's figures as plain text for Gemini to explain."""
    return (
        f"Model figures for {f['home']} (home) vs {f['away']} (away):\n"
        f"Elo rating: {f['home']} {f['home_elo']}, {f['away']} {f['away_elo']}\n"
        f"Elo-based home win chance: {f['elo_home_pct']}%\n"
        f"Expected goals: {f['home']} {f['home_xg']}, {f['away']} {f['away_xg']}\n"
        f"Poisson probabilities: home win {f['p_home']}%, draw {f['p_draw']}%, away win {f['p_away']}%"
    )

def ask(text_in, label, league_code, attachment=None):
    email = st.session_state.user_email
    add_message("user", label)

    # Follow the language of the message just sent
    st.session_state.lang = detect_lang(text_in)
    L = LABELS[st.session_state.lang]

    # Results, records and my-predictions questions are answered from data, free
    if results_intent(text_in):
        add_message("table", results_block(text_in, email, league_code))
        return

    # Tables and fixtures come straight from the football data (free, no model call)
    if not needs_credit(text_in):
        kind = table_intent(text_in)
        if kind == "table":
            add_message("table", standings_html(league_code))
            return
        if kind == "fixtures":
            add_message("table", fixtures_html(league_code))
            return

    paid = needs_credit(text_in)
    pair = find_team_rows(league_code, text_in) if paid else None

    # Run the model before charging, so no credit is spent on a match it cannot cover
    figs = None
    if paid and pair:
        figs = model_figures(league_code, pair[0], pair[1])
        if figs is None:
            add_message("assistant", NO_HISTORY[st.session_state.lang])
            return

    if paid and not is_owner(email) and get_credits(email) < 1:
        st.session_state.paywall = True
        add_message("assistant", L["paywall"])
        return

    if figs:
        context = (figures_block(figs) + "\n\n"
                   + prediction_context(league_code, figs["home"], figs["away"]))
        instruction = (
            f"\n\nUse exactly these percentages: Home win {figs['p_home']}%, "
            f"Draw {figs['p_draw']}%, Away win {figs['p_away']}%. Do not change them. "
            "Then give three short reasons that cite the figures above."
        )
    else:
        context = match_context(league_code)
        instruction = ""
    instruction = f"\n\nReply in {L['reply_in']}." + instruction

    question = f"{context}\n\nUser question: {text_in}{instruction}"
    content = question
    if attachment is not None:
        part = types.Part.from_bytes(data=attachment.getvalue(), mime_type=attachment.type)
        content = [part, question]

    text = ""
    for attempt in range(2):
        try:
            with st.spinner("Analysing..."):
                reply = st.session_state.chat.send_message(content)
            text = (reply.text or "").strip()
        except Exception:
            text = ""
        if text:
            break

    if not text:
        add_message("assistant", L["failed"])
        return

    # Guard: an unpaid answer with percentages counts as a prediction
    if not paid and not is_owner(email) and re.search(r"\d+\s*%", text):
        paid = True
        if get_credits(email) < 1:
            st.session_state.paywall = True
            add_message("assistant", L["was_prediction"])
            return

    if paid and not is_owner(email):
        spend_credit(email)

    probs = None
    if paid and figs:
        probs = (figs["p_home"], figs["p_draw"], figs["p_away"])
        log_prediction(email, league_code, pair[0], pair[1], probs)
        add_message("table", team_card(pair[0]["id"], pair[0]["name"], league_code)
                    + team_card(pair[1]["id"], pair[1]["name"], league_code))

    if st.session_state.reply_mode in ("Voice", "Both"):
        with st.spinner("Preparing voice..."):
            st.session_state.pending_voice = speak(text)

    # Reasons first, then the model's estimated chances at the bottom
    add_message("assistant", text)
    if probs:
        add_message("table", prob_bars(figs["home"], figs["away"], probs))

def transcribe(data):
    try:
        part = types.Part.from_bytes(data=data, mime_type="audio/wav")
        r = client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[part, "Transcribe this speech exactly. Reply with only the words spoken."],
        )
        return (r.text or "").strip()
    except Exception:
        return ""

def render_home(league_code):
    """Start screen shown before the first message: welcome, track record, fixtures, quick actions."""
    hero = (
        '<div class="hero">'
        '<h3>Welcome to Matchday Prediction</h3>'
        '<p>Pick a league, then check fixtures, tables and team form. '
        'Ask for a prediction when you want one. General questions are free.</p>'
        '<div class="steps">'
        '<div class="step"><b>1. Pick a league</b>Choose from the top five and the Champions League.</div>'
        '<div class="step"><b>2. Ask anything</b>Type, speak, or tap a quick action below.</div>'
        '<div class="step"><b>3. Get analysis</b>Predictions show estimated chances, not guarantees.</div>'
        '</div></div>'
    )
    st.markdown(hero, unsafe_allow_html=True)
    st.markdown(stats_card(prediction_stats(), "Track record: all predictions"),
                unsafe_allow_html=True)

    st.markdown('<p class="quick-title">Next matches</p>', unsafe_allow_html=True)
    matches, err = league_fixtures(league_code, FOOTBALL_KEY)
    if matches:
        for m in matches[:5]:
            home = html.escape(m["homeTeam"]["name"])
            away = html.escape(m["awayTeam"]["name"])
            when = fmt_kickoff(m["utcDate"])
            st.markdown(
                f'<div class="fx"><span>{home} vs {away}</span>'
                f'<span class="fx-date">{when}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("Fixtures are unavailable for this league right now. You can still ask questions.")

    st.markdown('<p class="quick-title">What would you like to know?</p>', unsafe_allow_html=True)
    for i in range(0, len(QUICK_ACTIONS), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            if i + j < len(QUICK_ACTIONS):
                label, question = QUICK_ACTIONS[i + j]
                with col:
                    st.button(
                        label,
                        key=f"qa_{i + j}",
                        on_click=pick_quick,
                        args=(question,),
                        use_container_width=True,
                    )

# ---------- League and reply mode ----------
c_league, c_mode = st.columns([3, 2], vertical_alignment="center")
with c_league:
    st.selectbox("League", list(LEAGUES.keys()), key="league")
with c_mode:
    st.radio("Reply", REPLY_MODES, key="reply_mode", horizontal=True)

league_code = LEAGUES[st.session_state.league]

# ---------- Start screen (empty chat) or chat box (has messages) ----------
if st.session_state.messages:
    chat_box = st.container(height=CHAT_HEIGHT, border=False)
else:
    render_home(league_code)

if current_attachment() is not None:
    st.markdown(
        f'<p class="attach-note">📎 {html.escape(current_attachment().name)} attached</p>',
        unsafe_allow_html=True,
    )

# ---------- Input row ----------
c_plus, c_text, c_mic, c_send = st.columns([1.2, 9, 1.6, 1.6], vertical_alignment="center")
with c_plus:
    with st.popover("+"):
        st.file_uploader(
            "Add a screenshot or PDF",
            type=ATTACH_TYPES,
            key=f"att_{st.session_state.att_n}",
        )
with c_text:
    st.text_input(
        "Message",
        key="draft",
        placeholder="Ask about a match or the table...",
        label_visibility="collapsed",
        on_change=submit_draft,
    )
with c_mic:
    with st.popover("🎤"):
        audio = st.audio_input("Record your question", key="rec")
with c_send:
    st.button("➤", on_click=submit_draft)

prompt = st.session_state.get("to_send", "")
st.session_state.to_send = ""

if prompt:
    att = current_attachment()
    st.audio(SEND_SOUND, format="audio/wav", autoplay=True)
    label = prompt if att is None else f"📎 {att.name}\n{prompt}"
    ask(prompt, label, league_code, attachment=att)
    st.session_state.att_n += 1
    st.rerun()
elif audio is not None:
    data = audio.getvalue()
    h = hashlib.md5(data).hexdigest()
    if h != st.session_state.last_audio:
        st.session_state.last_audio = h
        with st.spinner("Listening..."):
            heard = transcribe(data)
        if heard:
            st.audio(SEND_SOUND, format="audio/wav", autoplay=True)
            ask(heard, "🎤 " + heard, league_code)
            st.rerun()
        else:
            st.warning("I couldn't hear that clearly. Please record again.")

# ---------- Render history ----------
if st.session_state.messages:
    with chat_box:
        for m in st.session_state.messages:
            if m["role"] == "table":
                st.markdown(m["text"], unsafe_allow_html=True)
                continue
            safe = html.escape(m["text"]).replace("\n", "<br>")
            if m["role"] == "user":
                st.markdown(
                    f'<div class="row row-user">'
                    f'<div class="bubble bubble-user">{safe}</div>'
                    f'<div class="avatar avatar-user">You</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="row row-bot">'
                    f'<div class="avatar avatar-bot">MP</div>'
                    f'<div class="bubble bubble-bot">{safe}</div></div>',
                    unsafe_allow_html=True,
                )
        if st.session_state.get("pending_voice"):
            st.audio(st.session_state.pending_voice, format="audio/wav", autoplay=True)
            st.session_state.pending_voice = None

# ---------- Paywall: manual PayBill and access code ----------
if st.session_state.paywall:
    amount = PACK_SIZE * CREDIT_KSH
    st.info(f"Predictions use credits. {PACK_SIZE} credits cost KSh {amount}.")
    if PAYBILL_NUMBER == "not set" or ACCOUNT_NUMBER == "not set":
        st.warning("Payment details are not set up yet. Please check back soon.")
    else:
        st.markdown(
            f"**Pay with M-Pesa**\n\n"
            f"1. Go to **Lipa na M-Pesa → Paybill**\n"
            f"2. Paybill number: **{PAYBILL_NUMBER}**\n"
            f"3. Account number: **{ACCOUNT_NUMBER}**\n"
            f"4. Amount: **KSh {amount}**\n"
            f"5. Enter your PIN, then send us your M-Pesa confirmation code and your email. "
            f"Credits are added after we check the payment."
        )
    with st.form("redeem"):
        code_in = st.text_input("Enter your access code", type="password")
        redeem_submit = st.form_submit_button("Add credits")
    if redeem_submit:
        ok, msg = redeem_code(st.session_state.user_email, code_in)
        if ok:
            st.session_state.paywall = False
            st.rerun()
        else:
            st.error(msg)

# ---------- Owner stats and PayBill crediting (only visible to ADMIN_EMAIL) ----------
if is_owner(st.session_state.user_email):
    with st.sidebar.expander("📊 Owner stats"):
        packs = count_rows("redemptions")
        st.metric("Visits (all time)", count_events("visit"))
        st.metric("Visits (last 7 days)", count_events("visit", 7))
        st.metric("Sign-ups", count_events("signup"))
        st.metric("Unique people who signed in", count_unique_signins())
        st.metric("Sign-ins (total)", count_events("signin"))
        st.metric("Packs sold", packs)
        st.metric("Credits sold", packs * PACK_SIZE)
        st.metric("Revenue (KSh)", packs * int(PAY_PRICE))
        st.metric("Referrals rewarded", count_rows("referrals", rewarded=True))
        st.metric("Chats started", count_rows("conversations"))
        ps = prediction_stats()
        st.metric("Predictions made (all)", ps["total"])
        st.metric("Checked against results", ps["played"])
        st.metric("Correct", ps["correct"])
        st.metric("Wrong", ps["wrong"])
        st.metric("Awaiting result", ps["pending"])
        st.divider()
        st.markdown("**Credit a PayBill payment**")
        with st.form("owner_credit"):
            buyer_in = st.text_input("Buyer's email")
            ref_in = st.text_input("M-Pesa confirmation code")
            packs_in = st.number_input("Packs (KSh 100 each)", min_value=1, max_value=20, value=1, step=1)
            if st.form_submit_button("Add credits"):
                ok, msg = owner_credit(buyer_in, ref_in, int(packs_in))
                (st.success if ok else st.error)(msg)
