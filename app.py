import os
import io
import math
import wave
import struct
import html
import hashlib
from pathlib import Path
import streamlit as st
from google import genai
from google.genai import types

MODEL = "gemini-flash-latest"          # chat model
TRANSCRIBE_MODEL = "gemini-flash-latest"    # speech to text
TTS_MODEL = "gemini-2.5-flash-preview-tts"  # text to speech (voice replies)
VOICE_NAME = "Kore"
FREE_QUESTIONS = 3
CHAT_HEIGHT = 480
REPLY_MODES = ["Text", "Voice", "Both"]
ATTACH_TYPES = ["png", "jpg", "jpeg", "webp", "pdf"]

st.set_page_config(page_title="Study Buddy AI", page_icon="📚", layout="centered")

st.markdown("""
<style>
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }
.stApp { background: #F4FAF9; }
.block-container { max-width: 780px; padding-top: 1.5rem; }

/* Header card */
.brand {
    display: flex; align-items: center; gap: 14px;
    background: linear-gradient(135deg, #0F766E 0%, #115E59 100%);
    border-radius: 18px; padding: 16px 20px; margin-bottom: 14px;
    box-shadow: 0 6px 18px rgba(15, 118, 110, 0.18);
}
.brand-title { color: #FFFFFF; font-size: 1.5rem; font-weight: 700; margin: 0; letter-spacing: 0.2px; }
.brand-sub { color: #CCFBF1; font-size: 0.92rem; margin: 2px 0 0 0; }
.brand-badge {
    margin-left: auto; background: #FDE68A; color: #78350F;
    font-size: 0.72rem; font-weight: 700; padding: 4px 10px; border-radius: 999px;
}

/* Chat rows with avatars */
.row { display: flex; align-items: flex-end; gap: 10px; margin: 10px 0; }
.row-user { justify-content: flex-end; }
.row-bot { justify-content: flex-start; }
.avatar {
    width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.75rem; font-weight: 700;
}
.avatar-bot { background: #0F766E; color: #FFFFFF; }
.avatar-user { background: #FDE68A; color: #78350F; }
.bubble {
    padding: 11px 15px; line-height: 1.55; font-size: 0.97rem;
    max-width: 78%; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.bubble-user {
    background: #FFFFFF; color: #134E4A;
    border: 1px solid #99F6E4; border-left: 4px solid #F59E0B;
    border-radius: 16px 16px 4px 16px;
}
.bubble-bot {
    background: #0F766E; color: #F0FDFA;
    border-radius: 16px 16px 16px 4px;
}

/* Controls */
.stRadio > div { gap: 8px; }
.stRadio label p { font-weight: 600; color: #134E4A; }
div[data-testid="stPopover"] button { border-radius: 12px; }
.stButton > button {
    background: #F59E0B; color: #1C1917; border: none; font-weight: 700;
    border-radius: 12px;
}
.stButton > button:hover { background: #D97706; color: #FFFFFF; }
.stTextInput input { border-radius: 12px; }
.attach-note { color: #0F766E; font-size: 0.85rem; font-weight: 600; margin: 0 0 4px 0; }
</style>
""", unsafe_allow_html=True)

# ---------- Header ----------
st.markdown("""
<div class="brand">
    <div>
        <p class="brand-title">📚 Study Buddy AI</p>
        <p class="brand-sub">Learn step by step. Ask by text, voice, or file.</p>
    </div>
    <span class="brand-badge">Tutor</span>
</div>
""", unsafe_allow_html=True)

logo = Path(__file__).parent / "logo.jpg"
if logo.exists():
    st.image(str(logo), width=56)

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

@st.cache_resource
def get_client():
    return genai.Client(api_key=key)

client = get_client()

# ---------- Session state (safe even for sessions started earlier) ----------
if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction="You are a patient exam and homework tutor for students. When a student asks about a topic, explain it simply in small steps with one clear example. Then give one practice question and wait for their answer. If they are wrong, hint first and explain the mistake kindly. If they ask for a quiz, give 5 questions, one at a time. If they paste a homework question, guide them to the answer rather than just stating it. If they attach an image or PDF, read it carefully and guide them through it. Keep replies short and encouraging."
        ),
    )
st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_audio", None)
st.session_state.setdefault("used", 0)
st.session_state.setdefault("unlocked", False)
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
        st.session_state.to_send = text or "Please help me with this file."
    st.session_state.draft = ""

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
    st.session_state.used += 1
    st.session_state.messages.append({"role": "user", "text": label})

    content = text_in
    if attachment is not None:
        part = types.Part.from_bytes(data=attachment.getvalue(), mime_type=attachment.type)
        content = [part, text_in]

    text = ""
    for attempt in range(2):
        try:
            with st.spinner("Thinking..."):
                reply = st.session_state.chat.send_message(content)
            text = (reply.text or "").strip()
        except Exception:
            text = ""
        if text:
            break
    if not text:
        text = "I couldn't get an answer just now. Please try again or rephrase your question."
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

locked = (not st.session_state.unlocked) and st.session_state.used >= FREE_QUESTIONS

# ---------- Reply mode choice ----------
if not locked:
    st.radio("How should I answer?", REPLY_MODES, key="reply_mode", horizontal=True)

# ---------- Chat history (fixed-height box) ----------
chat_box = st.container(height=CHAT_HEIGHT, border=False)

# ---------- Attachment indicator ----------
if not locked and current_attachment() is not None:
    st.markdown(
        f'<p class="attach-note">📎 {html.escape(current_attachment().name)} attached</p>',
        unsafe_allow_html=True,
    )

# ---------- Input row (only when unlocked) ----------
audio = None
if not locked:
    c_plus, c_text, c_mic, c_send = st.columns([1, 11, 2, 2], vertical_alignment="bottom")
    with c_plus:
        with st.popover("+"):
            st.file_uploader(
                "Add a picture or PDF",
                type=ATTACH_TYPES,
                key=f"att_{st.session_state.att_n}",
            )
    with c_text:
        st.text_input(
            "Message",
            key="draft",
            placeholder="Ask a study question...",
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

if not locked:
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
                f'<div class="avatar avatar-bot">SB</div>'
                f'<div class="bubble bubble-bot">{safe}</div></div>',
                unsafe_allow_html=True,
            )
    if st.session_state.get("pending_voice"):
        st.audio(st.session_state.pending_voice, format="audio/wav", autoplay=True)
        st.session_state.pending_voice = None

# ---------- Lock message and access code (below the conversation) ----------
if locked:
    st.info("You've used your free questions. Get an access code to keep learning.")
    if PAY_LINK:
        st.markdown(f"👉 [Pay here to get your code]({PAY_LINK})")
    code = st.text_input("Enter your access code", type="password")
    if st.button("Unlock"):
        if code.strip() in CODES:
            st.session_state.unlocked = True
            st.rerun()
        else:
            st.error("That code is not valid. Check it and try again.")
