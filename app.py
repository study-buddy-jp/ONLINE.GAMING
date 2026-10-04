import os
import streamlit as st
from google import genai
from google.genai import types

st.title("Study Buddy")

key = os.environ.get("GEMINI_API_KEY") or st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def get_client():
    return genai.Client(api_key=key)

client = get_client()

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model="gemini-flash-lite-latest",
        config=types.GenerateContentConfig(
            system_instruction="You are a patient exam and homework tutor for students. When a student asks about a topic, explain it simply in small steps with one clear example. Then give one practice question and wait for their answer. If they are wrong, hint first and explain the mistake kindly. If they ask for a quiz, give 5 questions, one at a time. If they paste a homework question, guide them to the answer rather than just stating it. Keep replies short and encouraging."
        ),
    )
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

prompt = st.chat_input("Type your message")
if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    reply = st.session_state.chat.send_message(prompt)
    st.session_state.messages.append({"role": "assistant", "text": reply.text})
    with st.chat_message("assistant"):
        st.write(reply.text)