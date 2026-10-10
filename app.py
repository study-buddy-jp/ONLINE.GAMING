import os
import hashlib
import streamlit as st
from google import genai
from google.genai import types

# Change to "gemini-flash-latest" if you still get blank replies
MODEL = "gemini-flash-lite-latest"
FREE_QUESTIONS = 3

st.set_page_config(page_title="Study Buddy AI", page_icon="📚")

st.markdown("""
<style>
[data-testid="stChatMessage"] {
    border-radius: 16px;
    padding: 12px 16px;
    margin-bottom: 8px;
    background-color: #FFFFFF;
    border: 1px solid #D5DCFF;
}
h1 { color: #6C63FF; text-align: center; }
</style>
""", unsafe_allow_html=True)

st.title("📚 Study Buddy AI")
st.caption("Ask me anything about your studies. Type or speak.")

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
    st.session_state.messages.append({"role": "assistant", "text": text})

def transcribe(data):
    try:
        part = types.Part.from_bytes(data=data, mime_type="audio/wav")
        r = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[part, "Transcribe this speech exactly. Reply with only the words spoken."],
        )
        return (r.text or "").strip()
    except Exception:
        return ""

chat_area = st.container()

locked = (not st.session_state.unlocked) and st.session_state.used >= FREE_QUESTIONS
prompt = None
audio = None

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
else:
    with st.expander("🎤 Speak instead", expanded=True):
        audio = st.audio_input("Press the mic, speak, then press stop")
    prompt = st.chat_input("Type your message")

if prompt:
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
            ask(heard, "🎤 " + heard)
            st.rerun()
        else:
            st.warning("I couldn't hear that clearly. Please record again.")

with chat_area:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.write(m["text"])
