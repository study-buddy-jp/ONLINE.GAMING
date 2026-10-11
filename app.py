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

# Backup keyword check, used only if the classifier call fails
PAID_KEYWORDS = [
    "predict", "prediction", "probab", "estimate", "chance", "odds",
    "forecast", "who will win", "who wins", "likely", "win probability", "%",
    "stronger", "better", "beat", "win",
]

TERMS = """
**Welcome to Matchday Prediction.** Before you start, please read and accept these terms.

1. **What the app is:** An information and analysis tool for football fans. It shows fixtures and tables and gives estimated probabilities for discussion.
2. **Not betting advice:** Estimates are not guarantees and are not betting tips. We do not advise on bets.
3. **Age:** You must be 18 or older. You will be asked to confirm your age. This is based on your own answer.
4. **Your information:** To save your conversations, we store your email address, a scrambled form of your passcode, and the messages you send and receive. You can delete your history at any time from the sidebar. Do not send personal or sensitive information in your messages.
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
div[data-testid="stHorizontalBlock"] .stButton >
