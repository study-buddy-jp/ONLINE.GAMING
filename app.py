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
from pathlib import Path
import requests
import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client
from model import predict as model_predict
from mpesa import stk_push, normalise_phone

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
CREDIT_KSH = 20           # shillings per prediction credit (pack price = PACK_SIZE * CREDIT_KSH)
REFERRAL_CREDITS = 1      # free credits to the referrer when a referred friend's first pack is paid
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
    ("🔮 Predict a match", "Predict Arsenal vs Chelsea"),
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

# Terms are kept in terms.md, next to app.py, so they are easy to update and review
TERMS = (Path(__file__).parent / "terms.md").read_text(encoding="utf-8")

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

.paycard {
    background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%);
    border: 2px solid #F59E0B; border-radius: 18px;
    padding: 16px 18px; margin: 12px 0; box-shadow: 0 6px 18px rgba(245,158,11,0.25);
}
.paycard-title { color: #78350F; font-weight: 800; font-size: 1.1rem; margin: 0 0 4px 0; }
.paycard-price { color: #92400E; font-size: 1.6rem; font-weight: 800; margin: 2px 0 6px 0; }
.paycard-text { color: #78350F; font-size: 0.88rem; line-height: 1.45; margin: 0; }

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
.terms-small, .terms-small p, .terms-small li { font-size: 0.8rem; line-height: 1.4; color: #334155; }
</style>
""", unsafe_allow_html=True)

# ---------- Session state ----------
st.session_state.setdefault("user_email", None)
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
st.session_state.setdefault("pending_ref", "")

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

# Payment details, set in Streamlit secrets. Use the BUSINESS paybill and account, never a personal one.
PAY_LINK = get_secret("PAY_LINK")
PAY_PRICE = get_secret("PAY_PRICE", "100")
PAYBILL_NUMBER = get_secret("PAYBILL_NUMBER", "not set")
ACCOUNT_NUMBER = get_secret("ACCOUNT_NUMBER", "not set")

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

def ensure_user(email, ref_in=""):
    """Create the account the first time a Google sign-in is seen. No passcode is stored.
    Returns True when a new account was created."""
    if sb.table("users").select("email").eq("email", email).execute().data:
        return False
    sb.table("users").insert({
        "email": email,
        "salt": "",
        "pass_hash": "",
        "ref_code": secrets.token_hex(4).upper(),
        "created": now_iso(),
    }).execute()
    ref_in = (ref_in or "").strip().upper()
    if ref_in:
        referrer = sb.table("users").select("email").eq("ref_code", ref_in).execute().data
        if referrer and referrer[0]["email"] != email:
            sb.table("referrals").insert({
                "referee": email, "referrer": referrer[0]["email"],
            }).execute()
    log_event("signup", email)
    return True

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

# ----- Session persistence (a refresh keeps the same chat open) -----
def ensure_token():
    """Create a session row once per browser visit and keep its token in the page link."""
    tok = st.session_state.get("token")
    if not tok:
        tok = secrets.token_urlsafe(24)
        sb.table("sessions").insert({
            "token": tok,
            "email": st.session_state.get("user_email"),
            "conv_id": st.session_state.get("conv_id"),
            "created": now_iso(),
        }).execute()
        st.session_state.token = tok
        st.query_params["s"] = tok
    return tok

def save_progress(**fields):
    """Save the email and open chat so a refresh brings the user back to the same place."""
    tok = ensure_token()
    sb.table("sessions").update(fields).eq("token", tok).execute()

def end_session():
    tok = st.session_state.get("token")
    if tok:
        sb.table("sessions").delete().eq("token", tok).execute()
    st.session_state.token = None
    if "s" in st.query_params:
        del st.query_params["s"]

# Restore the open chat after a refresh, only if the Google account matches the saved session
if not st.session_state.restored:
    st.session_state.restored = True
    tok = st.query_params.get("s")
    if tok and st.user.is_logged_in:
        rows = sb.table("sessions").select("*").eq("token", tok).execute().data
        if rows and rows[0]["email"] == (st.user.email or "").strip().lower():
            row = rows[0]
            st.session_state.token = tok
            st.session_state.user_email = row["email"]
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
    """Called after a referred friend's first paid pack. Rewards only once."""
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
    code = code.strip()
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

# ---------- Sign in with Google (one tap, no passcode, no gate) ----------
if not st.user.is_logged_in:
    st.markdown(
        '<div class="hero"><h3>Welcome to Matchday Prediction</h3>'
        '<p>Sign in with Google to start. Fixtures, tables and form are free. '
        'Predictions use credits.</p></div>',
        unsafe_allow_html=True,
    )
    st.text_input("Referral code (optional)", key="pending_ref",
                  placeholder="A friend's referral code, if you have one")
    if st.button("Continue with Google", type="primary", use_container_width=True):
        st.login("google")
    st.caption("By continuing you agree to the Terms of Use below. Use is for people aged 18 or older.")
    with st.expander("Terms of Use"):
        st.markdown(f'<div class="terms-small">{TERMS}</div>', unsafe_allow_html=True)
    st.stop()

google_email = (st.user.email or "").strip().lower()
if not google_email:
    st.error("Google did not share an email address for this account. Try another Google account.")
    st.stop()

# First time this browser visit signs in: create the account if new and open a chat
if st.session_state.user_email != google_email:
    st.session_state.user_email = google_email
    ensure_user(google_email, st.session_state.get("pending_ref", ""))
    log_event("signin", google_email)
    if st.session_state.conv_id is None:
        st.session_state.conv_id = create_conversation(google_email)
        st.session_state.messages = []
    save_progress(email=google_email, conv_id=st.session_state.conv_id)

# ---------- Sidebar: account, chats, balance ----------
st.sidebar.markdown(f"**Signed in as**  \n{st.session_state.user_email}")

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
    st.logout()

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

with st.sidebar.expander("📄 Terms of Use"):
    st.markdown(f'<div class="terms-small">{TERMS}</div>', unsafe_allow_html=True)

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

CODES = [c.strip() for c in get_secret("ACCESS_CODES").split(",") if c.strip()]
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
