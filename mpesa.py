import base64
from datetime import datetime, timedelta, timezone
import requests

EAT = timezone(timedelta(hours=3))

def _base(env):
    return "https://api.safaricom.co.ke" if env == "production" else "https://sandbox.safaricom.co.ke"

def get_token(env, consumer_key, consumer_secret):
    r = requests.get(
        f"{_base(env)}/oauth/v1/generate?grant_type=client_credentials",
        auth=(consumer_key, consumer_secret),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def stk_push(env, consumer_key, consumer_secret, shortcode, passkey,
             callback_url, phone, amount, account_ref):
    """Ask the buyer's phone to confirm payment. phone format: 2547XXXXXXXX."""
    token = get_token(env, consumer_key, consumer_secret)
    timestamp = datetime.now(EAT).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": account_ref,
        "TransactionDesc": "Prediction credits",
    }
    r = requests.post(
        f"{_base(env)}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return r.status_code, r.json()
