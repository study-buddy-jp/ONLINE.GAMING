import os
import io
import math
import wave
import struct
import html
import hashlib
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
APP_TITLE = "⚽ Matchday Pulse"
APP_TAGLINE = "EPL fixtures, form, and match analysis. Ask by text, voice, or screenshot."
APP_ROLE_TAG = "EPL Analyst"

# Words that signal a prediction or estimate (the paid part)
PAID_KEYWORDS = [
    "predict", "prediction", "probab", "estimate", "chance", "odds",
    "forecast", "who will win", "who wins", "likely to win", "win probability", "%",
]

st.set_page_config(page_title="Matchday Pulse", page_icon="⚽", layout="centered")

st.markdown("""
<style>
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }
.stApp { background: #F5F8F4; }
.block-container { max-width: 780px; padding-top: 1rem; padding-bottom: 0.5rem; }
div[data-testid="stVerticalBlock"] { gap: 0.5rem; }
div[data-testid="stMarkdownContainer"] p { margin-bottom: 0; }

/* Keep + / text / mic / send on ONE line, even on phones */
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

/* Header card */
.brand {
    display: flex; align-items: center; gap: 14px;
    background: linear-gradient(135deg, #14532D 0%, #166534 100%);
    border-radius: 16px; padding: 12px 18px; margin-bottom: 6px;
    box-shadow: 0 4px 14px rgba(20, 83, 45, 0.20);
}
.brand-title { color: #FFFFFF; font-size: 1.3rem; font-weight: 700; margin: 0; }
.brand-sub { color: #DCFCE7; font-size: 0.88rem; margin: 2px 0 0 0; }
.brand-badge {
    margin-left: auto; background: #FACC15; color: #422006;
    font-size: 0.7rem; font-weight: 700; padding: 3px 9px; border-radius: 999px;
    white-space: nowrap;
}
.disclaimer { color: #6B7280; font-size: 0.78rem; margin: 2px 0 4px 0; }

/* Empty state */
.empty { color: #6B7280; text-align: center; font-size: 0.92rem; margin-top: 22%; line-height: 1.6; }

/* Chat rows */
.row { display: flex; align-items: flex-end; gap: 8px; margin: 6px 0; }
.row-user { justify-content: flex-end; }
.row-bot { justify-content: flex-start; }
.avatar {
    width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.7rem; font-weight: 700;
}
.avatar-bot { background: #166534; color: #FFFFFF; }
.avatar-user { background: #FACC15; color: #422006; }
.bubble {
    padding: 8px 12px; line-height: 1.45; font-size: 0.95rem;
    max-width: 78%; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.bubble-user {
    background: #FFFFFF; color: #14532D;
    border: 1px solid #BBF7D0; border-left: 3px solid #FACC15;
    border-radius: 14px 14px 4px 14px;
}
.bubble-bot {
    background: #166534; color: #F0FDF4;
    border-radius: 14px 14px 14px 4px;
}

/* Controls */
.stRadio > div { gap: 6px; }
.stRadio label p { font-weight: 600; color: #14532D; font-size: 0.88rem; }
.stButton > button {
    background: #FACC15; color: #422006; border: none; font-weight: 700;
    border-radius: 10px; padding: 0.25rem 0.6rem;
}
.stButton > button:hover { background: #EAB308; color: #FFFFFF; }
.stTextInput input { border-radius: 10px; padding: 0.4rem 0.6rem; }
div[data-testid="stPopover"] button { border-radius: 10px; padding: 0.25rem 0.5rem; }
.attach-note { color: #166534; font-size: 0.82rem; font-weight: 600; margin: 0; }
</style>
""", unsafe_allow_html=True)

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
FOOTBALL_KEY = get_secret("FOOTBALL_API_KEY")

@st.cache_resource
def get_client():
    return genai.Client(api_key=key)

client = get_client()

# ---------- Football data (cached to respect rate limits) ----------
@st.cache_data(ttl=900)
def epl_upcoming():
    if not FOOTBALL_KEY:
        return None
    try:
        r = requests.get(
            "https://api.football-data.org/v4/competitions/PL/matches",
            headers={"X-Auth-Token": FOOTBALL_KEY},
            params={"status": "SCHEDULED"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception:
        return None

@st.cache_data(ttl=3600)
def epl_table():
    if not FOOTBALL_KEY:
        return None
    try:
        r = requests.get(
            "https://api.football-data.org/v4/competitions/PL/standings",
            headers={"X-Auth-Token": FOOTBALL_KEY},
            timeout=10,
        )
        r.raise_for_status()
        standings = r.json().get("standings", [])
        return standings[0].get("table", []) if standings else None
    except Exception:
        return None

def fixtures_context(limit=10):
    matches = epl_upcoming()
    if not matches:
        return "Live fixture data is unavailable right now."
    lines = []
    for m in matches[:limit]:
        date = m["utcDate"][:16].replace("T", " ")
        lines.append(f"{date} UTC: {m['homeTeam']['name']} vs {m['awayTeam']['name']}")
    return "Upcoming Premier League fixtures:\n" + "\n".join(lines)

def table_context(limit=20):
    table = epl_table()
    if not table:
        return "League table is unavailable right now."
    lines = []
    for row in table[:limit]:
        lines.append(
            f"{row['position']}. {row['team']['name']}: P{row['playedGames']} "
            f"W{row['won']} D{row['draw']} L{row['lost']} "
            f"GF{row['goalsFor']} GA{row['goalsAgainst']} Pts{row['points']}"
        )
    return "Current Premier League table:\n" + "\n".join(lines)

def match_context():
    return fixtures_context() + "\n\n" + table_context()

# ---------- Session state (safe even for sessions started earlier) ----------
SYSTEM_PROMPT = (
    "You are Matchday Pulse, an English Premier League analyst for football fans. "
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

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_audio", None)
st.session_state.setdefault("unlocked", False)
st.session_state.setdefault("paywall", False)
st.session_state.setdefault("pending_voice", None)
st.session_state.setdefault("to_send", "")
st.session_state.setdefault("draft", "")
st.session_state.setdefault("reply_mode", "Text")
st.session_state.setdefault("att_n", 0)

def current_attachment():
    return st.session_state.get(f"att_{st.session_state.att_n}")

def submit_draft():
    text = st.session_state.get("draft", "").strip()
    att = current_attachment()
    if text or att is not None:
        st.session_state.to_send = text or "Please analyse this file."
    st.session_state.draft = ""

def is_paid_request(text):
    t = text.lower()
    return any(word in t for word in PAID_KEYWORDS)

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

def ask(text_in, label, attachment=None):
    st.session_state.messages.append({"role": "user", "text": label})

    # Predictions and estimates are paid: prompt for payment instead of answering
    if is_paid_request(text_in) and not st.session_state.unlocked:
        st.session_state.paywall = True
        st.session_state.messages.append({
            "role": "assistant",
            "text": "Predictions and probability estimates are part of the paid plan. "
                    "Get an access code below to unlock them. You can keep asking "
                    "general questions about fixtures, form, and the table for free.",
        })
        return

    question = f"{match_context()}\n\nUser question: {text_in}"
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
        text = "I couldn't get an analysis just now. Please try again or rephrase your question."
    elif st.session_state.reply_mode in ("Voice", "Both"):
        with st.spinner("Preparing voice..."):
            st.session_state.pending_voice = speak(text)
    st.session_state.messages.append({"role": "assistant", "text": text})

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

# ---------- Reply mode choice ----------
st.radio("How should I answer?", REPLY_MODES, key="reply_mode", horizontal=True)

# ---------- Chat history (fixed-height box) ----------
chat_box = st.container(height=CHAT_HEIGHT, border=False)

# ---------- Attachment indicator ----------
if current_attachment() is not None:
    st.markdown(
        f'<p class="attach-note">📎 {html.escape(current_attachment().name)} attached</p>',
        unsafe_allow_html=True,
    )

# ---------- Input row (always available) ----------
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
    ask(prompt, label, attachment=att)
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
            ask(heard, "🎤 " + heard)
            st.rerun()
        else:
            st.warning("I couldn't hear that clearly. Please record again.")

# ---------- Render history with avatars ----------
with chat_box:
    if not st.session_state.messages:
        st.markdown(
            '<div class="empty">Ask about this weekend\'s fixtures, a team\'s form,<br>'
            'or upload a table screenshot to get started.</div>',
            unsafe_allow_html=True,
        )
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

# ---------- Payment and access code (below the conversation, only when needed) ----------
if st.session_state.paywall and not st.session_state.unlocked:
    st.info("Predictions and estimates need an access code. Pay to unlock them.")
    if PAY_LINK:
        st.markdown(f"👉 [Pay here to get your code]({PAY_LINK})")
    code = st.text_input("Enter your access code", type="password")
    if st.button("Unlock"):
        if code.strip() in CODES:
            st.session_state.unlocked = True
            st.session_state.paywall = False
            st.rerun()
        else:
            st.error("That code is not valid. Check it and try again.")
