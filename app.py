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

MODEL = "gemini-flash-lite-latest"          # chat model
TRANSCRIBE_MODEL = "gemini-flash-latest"    # speech to text
TTS_MODEL = "gemini-2.5-flash-preview-tts"  # text to speech (voice replies)
VOICE_NAME = "Kore"
FREE_QUESTIONS = 3
CHAT_HEIGHT = 460

st.set_page_config(page_title="Study Buddy AI", page_icon="📚", layout="centered")

st.markdown("""
<style>
#MainMenu, footer { visibility: hidden; }
.block-container { max-width: 760px; padding-top: 2rem; }
.app-title { font-size: 2rem; font-weight: 700; color: #3F3D8F; margin: 0; }
.app-sub { color: #6B7280; margin: 2px 0 12px 0; }
.row-user { display: flex; justify-content: flex-end; margin: 8px 0; }
.row-bot { display: flex; justify-content: flex-start; margin: 8px 0; }
.bubble-user {
    background: #6C63FF; color: #FFFFFF; padding: 10px 14px;
    border-radius: 16px 16px 4px 16px; max-width: 75%; line-height: 1.5;
    box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}
.bubble-bot {
    background: #FFFFFF; color: #1F2937; border: 1px solid #E5E7EB;
    padding: 10px 14px; border-radius: 16px 16px 16px 4px; max-width: 80%;
    line-height: 1.5; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
</style>
""", unsafe_allow_html=True)

# ---------- Header ----------
col1, col2 = st.columns([1, 5], vertical_alignment="center")
with col1:
    logo = Path(__file__).parent / "logo.jpg"
    if logo.exists():
        st.image(str(logo), width=64)
with col2:
    st.markdown('<div class="app-title">Study Buddy AI</div>', unsafe_allow_html=True)
st.markdown('<div class="app-sub">Ask me anything about your studies. Type or speak.</div>',
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

@st.cache_resource
def get_client():
    return genai.Client(api_key=key)

client = get_client()

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction="You are a patient exam and homework tutor for students. When a student asks about a topic, explain it simply in small steps with one clear example. Then give one practice question and wait for their answer. If they are wrong, hint first and explain the mistake kindly. If they ask for a quiz, give 5 questions, one at a time. If they paste a homework question, guide them to the answer rather than just stating it. Keep replies short and encouraging."
        ),
    )
    st.session_state.messages = []
    st.session_state.last_audio = None
    st.session_state.used = 0
    st.session_state.unlocked = False
    st.session_state.pending_voice = None
    st.session_state.to_send = ""
    st.session_state.draft = ""

def submit_draft():
    text = st.session_state.get("draft", "").strip()
    if text:
        st.session_state.to_send = text
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

def ask(text_in, label):
    st.session_state.used += 1
    st.session_state.messages.append({"role": "user", "text": label})
    text = ""
    for attempt in range(2):
        try:
            with st.spinner("Thinking..."):
                reply = st.session_state.chat.send_message(text_in)
            text = (reply.text or "").strip()
        except Exception:
            text = ""
        if text:
            break
    if not text:
        text = "I couldn't get an answer just now. Please try again or rephrase your question."
    else:
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

# ---------- Chat history (fixed-height box) ----------
chat_box = st.container(height=CHAT_HEIGHT, border=False)

# ---------- Input row (only when unlocked) ----------
audio = None
if not locked:
    c_text, c_mic, c_send = st.columns([12, 2, 2], vertical_alignment="bottom")
    with c_text:
        st.text_input(
            "Message",
            key="draft",
            placeholder="Type your message...",
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
        st.audio(SEND_SOUND, format="audio/wav", autoplay=True)
        ask(prompt, prompt)
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

# ---------- Render history inside the box ----------
with chat_box:
    for m in st.session_state.messages:
        safe = html.escape(m["text"]).replace("\n", "<br>")
        if m["role"] == "user":
            st.markdown(
                f'<div class="row-user"><div class="bubble-user">{safe}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="row-bot"><div class="bubble-bot">{safe}</div></div>',
                unsafe_allow_html=True,
            )
    if st.session_state.pending_voice:
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
