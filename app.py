
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="kQ Trading ",
    page_icon="🛡️"
)

st.title("🛡️ Binary Trading ")



# Fictional account balance
if "balance" not in st.session_state:
    st.session_state.balance = 1000.0

if "history" not in st.session_state:
    st.session_state.history = []

st.subheader("📊 Fictional Trading Dashboard")

st.metric(
    " Balance",
    f"KSh {st.session_state.balance:,.2f}"
)

st.caption("The balance is .")

# Simulated deposit
st.subheader("💰 Simulated Deposit")

amount = st.number_input(
    "Enter  amount (KSh)",
    min_value=10.0,
    value=500.0,
    step=50.0
)

if st.button("Simulate Deposit"):
    st.session_state.balance += amount
    st.session_state.history.append({
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Type": "Fictional deposit",
        "Amount": f"KSh {amount:,.2f}",
        "Status": "SIMULATED — NOT PAID"
    })
    st.warning("Demo deposit recorded. No money was received.")

# Simulated withdrawal
st.subheader("🏦 Simulated Withdrawal")

withdrawal = st.number_input(
    "Withdrawal amount (KSh)",
    min_value=10.0,
    value=200.0,
    step=50.0
)

if st.button("Simulate Withdrawal"):
    if withdrawal <= st.session_state.balance:
        st.session_state.history.append({
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Type": "Fictional withdrawal request",
            "Amount": f"KSh {withdrawal:,.2f}",
            "Status": "SIMULATED — NOT SENT"
        })
        st.info("Illustrative request recorded. No money was sent.")
    else:
        st.warning("Insufficient fictional balance.")

# Transaction history
st.subheader("🧾  Transaction History")

if st.session_state.history:
    st.dataframe(
        st.session_state.history,
        use_container_width=True
    )
else:
    st.write("No simulated transactions yet.")

# Scam awareness examples
st.subheader("🚨 KQBINARY Trading ")

st.markdown("""
- **Guaranteed profits:** Nobody can guarantee trading profits.
- **Fake testimonials:** Screenshots can be fabricated.
- **Urgent deposits:** Scammers may pressure people to pay quickly.
- **Withdrawal fees:** Be suspicious of unexpected payments
  demanded to release supposed profits.
- **Fake balances:** A number displayed on a website is not
  proof that money exists.
""")

st.info(
    "Always verify transactions through your official bank "
    "or payment provider. This application does not connect "
    "to a broker, M-Pesa, or any real payment system."
)
