import os
import io
import re
import math
import wave
import struct
import html
import hmac
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
import streamlit as st
from google import genai
from google.genai import types

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
DB_PATH = Path(__file__).parent / "matchday.db"
HISTORY_LIMIT = 20
PACK_SIZE = 5   # prediction credits per access code
MIN_AGE = 18
NEW_CHAT_TITLE = "New chat"
EAT = timezone(timedelta(hours=3))  # Nairobi time

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
    ("🔥 Best form", "Which teams have the best form right now?"),
    ("📊 Explain a stat", "Explain what goals for and goals against tell me about a team."),
    ("🆚 Compare two teams", "Compare the two strongest teams in this league."),
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

TERMS = """
**Welcome to Matchday Prediction.** Before you start, please read and accept these terms.

1. **What the app is:** An information and analysis tool for football fans. It shows fixtures and tables and gives estimated probabilities for discussion.
2. **Not betting advice:** Estimates are not guarantees and are not betting tips. We do not advise on bets.
3. **Age:** You must be 18 or older. You will be asked to confirm your age. This is based on your own answer.
4. **Your information:** To save your conversations, we store your email address, a scrambled form of your passcode, and the messages you send and receive. You can delete your chats at any time from the sidebar. Do not send personal or sensitive information in your messages.
5. **Prediction credits:** Predictions use credits. Credits are bought with an access code after payment is confirmed. Each code gives a fixed number of credits, can be used once, and is not refundable after it is redeemed. Codes are personal and must not be shared.
6. **Accuracy:** Data comes from third-party sources and may be delayed or incomplete. We are not liable for decisions made from the app.
7. **Changes:** We may update these terms. Continued use means you accept the current version.
"""

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
st.session_state.setdefault("accepted_terms", False)
st.session_state.setdefault("age_ok", False)
st.session_state.setdefault("age_blocked", False)
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

# ---------- Step 1: terms ----------
if not st.session_state.accepted_terms:
    st.markdown(TERMS)
    agree = st.checkbox("I have read and accept the terms.")
    if st.button("Continue", disabled=not agree):
        st.session_state.accepted_terms = True
        st.rerun()
    st.stop()

# ---------- Step 2: age check ----------
if st.session_state.age_blocked:
    st.error(f"Sorry, you must be {MIN_AGE} or older to use {APP_NAME}, so you can't continue.")
    st.stop()

if not st.session_state.age_ok:
    st.markdown("### Confirm your age")
    with st.form("age"):
        age_txt = st.text_input("How old are you?", placeholder="e.g. 21")
        age_submit = st.form_submit_button("Continue")
    if age_submit:
        age_clean = age_txt.strip()
        if not age_clean.isdigit() or not (1 <= int(age_clean) <= 120):
            st.error("Please enter your age as a number.")
        elif int(age_clean) < MIN_AGE:
            st.session_state.age_blocked = True
            st.rerun()
        else:
            st.session_state.age_ok = True
            st.rerun()
    st.stop()

# ---------- Storage ----------
@st.cache_resource
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(email TEXT PRIMARY KEY, salt TEXT, pass_hash TEXT, created TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS conversations "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, title TEXT, created TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS chat_messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, email TEXT, "
        "role TEXT, text TEXT, created TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS wallet "
        "(email TEXT PRIMARY KEY, credits INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS redemptions "
        "(code TEXT PRIMARY KEY, email TEXT, created TEXT)"
    )
    con.commit()
    con.close()
    return True

init_db()

def db_exec(sql, args=()):
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()

def db_insert_id(sql, args=()):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()

def hash_pass(passcode, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", passcode.encode(), bytes.fromhex(salt_hex), 200_000
    ).hex()

def sign_in(email, passcode):
    """Returns (ok, message). Creates the account the first time an email is used."""
    email = email.strip().lower()
    if "@" not in email or "." not in email:
        return False, "Please enter a valid email address."
    rows = db_exec("SELECT salt, pass_hash FROM users WHERE email=?", (email,))
    if rows:
        salt, stored = rows[0]
        if hmac.compare_digest(hash_pass(passcode, salt), stored):
            return True, email
        return False, "Wrong passcode for this email."
    if len(passcode) < 6:
        return False, "Choose a passcode of at least 6 characters."
    salt = secrets.token_hex(16)
    db_exec(
        "INSERT INTO users (email, salt, pass_hash, created) VALUES (?,?,?,?)",
        (email, salt, hash_pass(passcode, salt), datetime.now().isoformat()),
    )
    return True, email

# ----- Conversations -----
def create_conversation(email):
    return db_insert_id(
        "INSERT INTO conversations (email, title, created) VALUES (?,?,?)",
        (email, NEW_CHAT_TITLE, datetime.now().isoformat()),
    )

def list_conversations(email):
    return db_exec(
        "SELECT id, title FROM conversations WHERE email=? ORDER BY id DESC LIMIT 30",
        (email,),
    )

def load_conv_messages(conv_id):
    rows = db_exec(
        "SELECT role, text FROM chat_messages WHERE conv_id=? ORDER BY id",
        (conv_id,),
    )
    return [{"role": r, "text": t} for r, t in rows]

def add_message(role, text):
    st.session_state.messages.append({"role": role, "text": text})
    email = st.session_state.user_email
    conv_id = st.session_state.conv_id
    if email and conv_id:
        db_exec(
            "INSERT INTO chat_messages (conv_id, email, role, text, created) VALUES (?,?,?,?,?)",
            (conv_id, email, role, text, datetime.now().isoformat()),
        )
        if role == "user":
            # Name the chat after its first question
            db_exec(
                "UPDATE conversations SET title=? WHERE id=? AND title=?",
                (text[:40], conv_id, NEW_CHAT_TITLE),
            )

def start_new_chat():
    st.session_state.conv_id = create_conversation(st.session_state.user_email)
    st.session_state.messages = []
    st.session_state.paywall = False
    st.session_state.pop("chat", None)

def open_chat(conv_id):
    st.session_state.conv_id = conv_id
    st.session_state.messages = load_conv_messages(conv_id)
    st.session_state.paywall = False
    st.session_state.pop("chat", None)

def delete_all_chats():
    email = st.session_state.user_email
    db_exec("DELETE FROM chat_messages WHERE email=?", (email,))
    db_exec("DELETE FROM conversations WHERE email=?", (email,))
    start_new_chat()

# ----- Credits -----
def get_credits(email):
    rows = db_exec("SELECT credits FROM wallet WHERE email=?", (email,))
    return rows[0][0] if rows else 0

def spend_credit(email):
    db_exec(
        "UPDATE wallet SET credits = credits - 1 WHERE email=? AND credits > 0",
        (email,),
    )

def redeem_code(email, code):
    code = code.strip()
    if code not in CODES:
        return False, "That code is not valid. Check it and try again."
    if db_exec("SELECT email FROM redemptions WHERE code=?", (code,)):
        return False, "That code has already been used."
    db_exec(
        "INSERT INTO redemptions (code, email, created) VALUES (?,?,?)",
        (code, email, datetime.now().isoformat()),
    )
    db_exec(
        "INSERT INTO wallet (email, credits) VALUES (?, ?) "
        "ON CONFLICT(email) DO UPDATE SET credits = credits + excluded.credits",
        (email, PACK_SIZE),
    )
    return True, f"{PACK_SIZE} prediction credits added."

# ---------- Step 3: sign in ----------
if not st.session_state.user_email:
    st.markdown("### Sign in to keep your conversations")
    st.caption("New here? Enter an email and choose a passcode. Returning? Use the same passcode.")
    with st.form("signin"):
        email_in = st.text_input("Email")
        pass_in = st.text_input("Passcode (at least 6 characters)", type="password")
        submitted = st.form_submit_button("Continue")
    if submitted:
        ok, result = sign_in(email_in, pass_in)
        if ok:
            st.session_state.user_email = result
            # Every sign-in starts a fresh chat; older chats stay in the sidebar
            st.session_state.conv_id = create_conversation(result)
            st.session_state.messages = []
            st.session_state.paywall = False
            st.session_state.pop("chat", None)
            st.rerun()
        else:
            st.error(result)
    st.stop()

# ---------- Sidebar: account, chats, credits ----------
st.sidebar.markdown(f"**Signed in as**  \n{st.session_state.user_email}")
st.sidebar.markdown(f"**Prediction credits:** {get_credits(st.session_state.user_email)}")

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
    st.session_state.user_email = None
    st.session_state.conv_id = None
    st.session_state.messages = []
    st.session_state.paywall = False
    st.session_state.pop("chat", None)
    st.rerun()

st.sidebar.caption("Credits stay on your account when you delete chats.")

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

def get_secret(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return default

key = get_secret("GEMINI_API_KEY")
if not key:
    st.error("The app is not set up yet (API key missing).")
    st.stop()

CODES = [c.strip() for c in get_secret("ACCESS_CODES").split(",") if c.strip()]
PAY_LINK = get_secret("PAY_LINK")
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

def fmt_kickoff(utc_str):
    """Turn football-data's UTC time into Nairobi time, e.g. 'Sat 18 Oct, 17:30'."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00")).astimezone(EAT)
    return dt.strftime("%a %d %b, %H:%M")

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
            f"{row['position']}. {row['team']['name']}: P{row['playedGames']} "
            f"W{row['won']} D{row['draw']} L{row['lost']} "
            f"GF{row['goalsFor']} GA{row['goalsAgainst']} Pts{row['points']}"
        )
    return "Current table:\n" + "\n".join(lines)

def match_context(code):
    return fixtures_context(code) + "\n\n" + table_context(code)

# ---------- Chat setup ----------
SYSTEM_PROMPT = (
    "You are Matchday Prediction, a football match analyst for fans of top European leagues. "
    "Use only the fixture and table data provided in each message for facts such as "
    "results, positions, and upcoming matches. If the data is missing or does not cover "
    "something, say so instead of guessing. When asked about a match, cover: recent form, "
    "league position, home and away strength, goals scored and conceded, and key factors "
    "such as injuries or motivation if the user mentions them. Give home win, draw, and "
    "away win probabilities that add up to 100%, label them as estimates, and give 3 short "
    "reasons. Never present a prediction as certain, never give betting tips, and never "
    "encourage betting. If asked about betting, briefly explain that you analyse matches "
    "but do not advise on bets. If the user attaches a screenshot or PDF of a table or "
    "stats, read it carefully and use it. Keep replies concise and clear."
)

def gemini_history(msgs):
    out = []
    for m in msgs[-HISTORY_LIMIT:]:
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

def ask(text_in, label, league_code, attachment=None):
    email = st.session_state.user_email
    add_message("user", label)

    # Step 1: decide whether this message costs a credit, before answering
    paid = needs_credit(text_in)
    if paid and get_credits(email) < 1:
        st.session_state.paywall = True
        add_message(
            "assistant",
            "Predictions and probability estimates use prediction credits, and you have none left. "
            "Get an access code below to add more. General questions about fixtures, form, "
            "and the table are still free.",
        )
        return

    question = f"{match_context(league_code)}\n\nUser question: {text_in}"
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
        add_message("assistant", "I couldn't get an analysis just now. Please try again or rephrase your question.")
        return

    # Step 2: guard. If an unpaid answer contains percentages, treat it as a prediction
    if not paid and re.search(r"\d+\s*%", text):
        paid = True
        if get_credits(email) < 1:
            st.session_state.paywall = True
            add_message(
                "assistant",
                "That was a prediction, which uses prediction credits. Get an access code below to add more.",
            )
            return

    # Step 3: charge only after a real answer was produced
    if paid:
        spend_credit(email)

    if st.session_state.reply_mode in ("Voice", "Both"):
        with st.spinner("Preparing voice..."):
            st.session_state.pending_voice = speak(text)
    add_message("assistant", text)

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
    """Start screen shown before the first message: welcome, fixtures, quick actions."""
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

# ---------- Buy or redeem credits (only when needed) ----------
if st.session_state.paywall:
    st.info("Predictions use credits. Pay to get an access code, then enter it to add credits.")
    if PAY_LINK:
        st.markdown(f"👉 [Pay here to get your code]({PAY_LINK})")
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
