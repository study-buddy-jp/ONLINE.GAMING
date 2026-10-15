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

MODEL = "gemini-flash-lite-latest"
TRANSCRIBE_MODEL = "gemini-flash-latest"
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_NAME = "Kore"
CHAT_HEIGHT = 340
REPLY_MODES = ["Text", "Voice", "Both"]
ATTACH_TYPES = ["png", "jpg", "jpeg", "webp", "pdf"]
APP_NAME = "Matchday Prediction"
APP_TITLE = f"⚽ {APP_NAME}"
APP_TAGLINE = "Fixtures, form, and match analysis across top leagues. Ask by text, voice, or screenshot."
APP_ROLE_TAG = "Match Analyst"
HISTORY_LIMIT = 20
PACK_SIZE = 5
CREDIT_KSH = 20
REFERRAL_CREDITS = 1
NEW_CHAT_TITLE = "New chat"
EAT = timezone(timedelta(hours=3))
RECENT_N = 8
H2H_N = 5

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

PAID_KEYWORDS = [
    "predict", "prediction", "probab", "estimate", "chance", "odds",
    "forecast", "who will win", "who wins", "likely", "win probability", "%",
    "stronger", "better", "beat", "win",
]

GENERAL_KEYWORDS = [
    "table", "fixture", "fixtures", "form", "schedule", "explain",
    "history", "head to head", "standings",
]

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
div[data-testid="stHorizontalBlock"] .stButton > button { min-height: 2.5rem; width: 100%; }
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
    font-size: 0.7rem; font-weight: 700; padding: 3px 9px; border-radius: 999px; white-space: nowrap;
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
.pbar { flex: 1; background: #DBEAFE; border-radius: 999px;
