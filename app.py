"""
Streamlit Global Currency Converter with Visual Analytics
Uses exchangerate.host (no API key needed) for live & historical rates.

Save as: app.py
Run: streamlit run app.py
"""

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import re
from typing import Tuple, Dict, Any

# ---------------------------
# Configuration / Constants
# ---------------------------
API_BASE = "https://api.exchangerate.host"
TOP_10 = ["USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "CNY", "SEK", "NZD"]  # most-traded / popular set
DEFAULT_BASE = "USD"
DEFAULT_TARGET = "EUR"
MAX_HISTORY_DAYS = 365  # safety cap for timeseries requests

# ---------------------------
# Helper functions (modular)
# ---------------------------

@st.cache_data(ttl=60*15)  # cache for 15 minutes
def fetch_symbols() -> Dict[str, Any]:
    """Fetch supported currency symbols from exchangerate.host"""
    res = requests.get(f"{API_BASE}/symbols", timeout=10)
    res.raise_for_status()
    data = res.json()
    # structure: { 'symbols': { 'USD': {description:'United States Dollar'}, ... } }
    return data.get("symbols", {})

@st.cache_data(ttl=60*5)
def fetch_latest(base: str = "USD") -> Dict[str, float]:
    """Fetch latest rates with given base currency"""
    res = requests.get(f"{API_BASE}/latest", params={"base": base}, timeout=10)
    res.raise_for_status()
    return res.json().get("rates", {})

@st.cache_data(ttl=60*60)
def fetch_timeseries(base: str, target: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch historical timeseries for a currency pair (start_date and end_date as YYYY-MM-DD)"""
    # safety: ensure not querying an excessive range
    sd = datetime.fromisoformat(start_date)
    ed = datetime.fromisoformat(end_date)
    if (ed - sd).days > MAX_HISTORY_DAYS:
        sd = ed - timedelta(days=MAX_HISTORY_DAYS)
        start_date = sd.strftime("%Y-%m-%d")

    params = {
        "start_date": start_date,
        "end_date": end_date,
        "base": base,
        "symbols": target
    }
    res = requests.get(f"{API_BASE}/timeseries", params=params, timeout=15)
    res.raise_for_status()
    j = res.json()
    # j['rates'] is { 'YYYY-MM-DD': {'TARGET': value}, ... }
    records = []
    for d, rate_obj in sorted(j.get("rates", {}).items()):
        records.append({"date": d, "rate": rate_obj.get(target)})
    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df

def convert_currency(amount: float, base: str, target: str) -> Tuple[float, Dict[str, Any]]:
    """Convert using the convert endpoint (single call)"""
    params = {"from": base, "to": target, "amount": amount}
    res = requests.get(f"{API_BASE}/convert", params=params, timeout=10)
    res.raise_for_status()
    j = res.json()
    return j.get("result"), j

def parse_nl_input(text: str) -> Tuple[float, str, str]:
    """
    Parse natural-language text like:
      - "convert 500 USD to PKR"
      - "1000 eur in usd"
      - "2500 pounds to usd" (common name currency mapping)
    Returns: (amount, base_code, target_code)
    If parsing fails, raises ValueError
    """
    # simple regex: number + currency + (to|in) + currency
    text = text.strip()
    # capture amount (float), then currency tokens (3-letter or words)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]{3,}|[A-Za-z]{3})\s*(?:to|in)\s*([A-Za-z]{3,})", text, re.IGNORECASE)
    if m:
        amt = float(m.group(1))
        a = m.group(2).upper()
        b = m.group(3).upper()
        # if provided tokens are full words (like 'pounds' or 'rupee'), try mapping common words -> codes
        a_code = word_to_currency_code(a)
        b_code = word_to_currency_code(b)
        if a_code and b_code:
            return amt, a_code, b_code
        # fallback: if already 3-letter codes, use directly
        if len(a) == 3 and len(b) == 3:
            return amt, a, b
    raise ValueError("Could not parse natural language input. Try format: 'convert 500 USD to PKR'")

# small mapping for common currency words -> 3-letter codes; extendable
COMMON_CURY = {
    "DOLLAR": "USD", "DOLLARS": "USD", "USD": "USD",
    "EURO": "EUR", "EUROS": "EUR", "EUR": "EUR",
    "POUND": "GBP", "POUNDS": "GBP", "STERLING": "GBP", "GBP": "GBP",
    "RUPEE": "PKR", "PKR": "PKR", "INR": "INR",
    "YEN": "JPY", "JPY": "JPY",
    "YUAN": "CNY", "RENMINBI": "CNY", "CNY": "CNY",
    "SWISS": "CHF", "FRANC": "CHF", "CHF": "CHF",
    "AUD": "AUD", "CAD": "CAD", "NZD": "NZD", "SEK": "SEK"
}

def word_to_currency_code(token: str) -> str:
    tok = token.upper()
    # strip trailing punctuation
    tok = re.sub(r"[^A-Z]", "", tok)
    if tok in COMMON_CURY:
        return COMMON_CURY[tok]
    if len(tok) == 3:  # already a code
        return tok
    return None

# ---------------------------
# Visualization helpers
# ---------------------------

def plot_top10_rates(base: str, symbols: Dict[str, Any]):
    """Bar chart comparing the base -> TOP_10 rates"""
    rates = fetch_latest(base)
    # build DataFrame for TOP_10 (if some missing, drop)
    rows = []
    for code in TOP_10:
        v = rates.get(code)
        if v is not None:
            rows.append({"currency": code, "rate": v, "name": symbols.get(code, {}).get("description", "")})
    if not rows:
        st.info("No rates available to plot for top currencies.")
        return
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="currency", y="rate", hover_data=["name"], title=f"Base {base} → Top currencies")
    st.plotly_chart(fig, use_container_width=True)

def plot_timeseries(df: pd.DataFrame, base: str, target: str):
    """Line chart for the timeseries DF (index=date, column rate)"""
    if df.empty:
        st.info("No historical data to show.")
        return
    df_plot = df.reset_index()
    df_plot.columns = ["date", "rate"]
    fig = px.line(df_plot, x="date", y="rate", title=f"{base} → {target} (historical)")
    fig.update_layout(xaxis_title="Date", yaxis_title=f"Rate ({target} per {base})")
    st.plotly_chart(fig, use_container_width=True)

def plot_pie_distribution(base: str, symbols: Dict[str, Any]):
    """Pie chart that shows relative value of top currencies vs base (for visual demo)"""
    rates = fetch_latest(base)
    rows = []
    for code in TOP_10:
        v = rates.get(code)
        if v:
            rows.append({"currency": code, "value": v})
    if not rows:
        return
    df = pd.DataFrame(rows)
    fig = px.pie(df, names="currency", values="value", title="Relative rates (visual comparison)")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------
# Streamlit UI layout
# ---------------------------

st.set_page_config(page_title="Global Currency Converter & Analytics", layout="wide", initial_sidebar_state="expanded")

# Top-level custom styling for a luxurious dark/light toggle (simple)
st.markdown("""
<style>
.header {
    background: linear-gradient(90deg,#0f172a,#0b1220);
    padding: 18px;
    border-radius: 12px;
    color: white;
}
.big-number {
    font-size: 28px;
    font-weight: 700;
}
.small-muted { color: #9aa4b2; }
.card {
    background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00));
    padding: 12px;
    border-radius: 10px;
    box-shadow: 0 6px 20px rgba(2,6,23,0.6);
}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="header"><h1 style="margin:0">💱 Global Currency Converter — Lux Dashboard</h1><div class="small-muted">Real-time conversions · Historical trends · Top currency analytics</div></div>', unsafe_allow_html=True)
st.write("")  # spacing

# Sidebar controls
with st.sidebar:
    st.header("Controls")
    symbols = fetch_symbols()
    currency_codes = sorted(symbols.keys())
    # allow quick selection lists: show codes and description in dropdown labels
    def label(code):
        return f"{code} — {symbols.get(code, {}).get('description','')}"
    base_sel = st.selectbox("Base currency", options=currency_codes, index=currency_codes.index(DEFAULT_BASE) if DEFAULT_BASE in currency_codes else 0, format_func=lambda x: label(x))
    target_sel = st.selectbox("Target currency", options=currency_codes, index=currency_codes.index(DEFAULT_TARGET) if DEFAULT_TARGET in currency_codes else 1, format_func=lambda x: label(x))
    auto_refresh = st.checkbox("Auto-refresh rates every 5 minutes", value=False)
    refresh_btn = st.button("Refresh rates now")
    st.markdown("---")
    st.markdown("**Natural language input** (try: `convert 500 USD to PKR`)")
    nl_text = st.text_input("Or paste description here", value="")
    st.markdown("---")
    st.markdown("Display options")
    days_history = st.radio("History range for trend", options=["7 days", "30 days", "90 days"], index=1)
    show_pie = st.checkbox("Show pie distribution", value=True)
    show_top10 = st.checkbox("Show top-10 bar chart", value=True)
    st.markdown("---")
    st.caption("Data provider: exchangerate.host (no API key required).")

# main content columns
col1, col2 = st.columns([1, 1.4])

# Left column: inputs & conversion
with col1:
    st.subheader("Convert currency")
    # First allow user to enter amount or parse from NLP input
    # If user provided nl_text, try parse
    parsed = None
    if nl_text.strip():
        try:
            amt_nl, base_nl, target_nl = parse_nl_input(nl_text)
            parsed = (amt_nl, base_nl, target_nl)
            st.success(f"Parsed: {amt_nl} {base_nl} → {target_nl}")
            # Offer to fill the inputs automatically
            if st.button("Use parsed values"):
                amount = amt_nl
                base_sel = base_nl
                target_sel = target_nl
        except ValueError:
            st.warning("Could not parse the natural language input. Use format: 'convert 500 USD to PKR'")

    # numeric input plus dropdowns (these reflect sidebar selections but are visible here too)
    amount = st.number_input("Amount", min_value=0.0, value=100.0, step=1.0, format="%.2f")
    base = st.selectbox("From (base)", currency_codes, index=currency_codes.index(base_sel), format_func=lambda x: label(x))
    target = st.selectbox("To (target)", currency_codes, index=currency_codes.index(target_sel), format_func=lambda x: label(x))
    if st.button("Convert"):
        try:
            converted_val, meta = convert_currency(amount, base, target)
            st.success(f"{amount:,.2f} {base}  →  {converted_val:,.2f} {target}")
            st.write("Details:")
            st.json({k: v for k, v in meta.items() if k in ("query", "info", "date", "historical")})
        except Exception as e:
            st.error(f"Conversion failed: {e}")
    # Quick convert preview (auto)
    try:
        preview_val, _ = convert_currency(amount, base, target)
        st.markdown(f"**Quick preview:** {amount:,.2f} {base} = **{preview_val:,.2f} {target}**")
    except Exception as e:
        st.info("Preview unavailable: " + str(e))

    st.markdown("---")
    st.subheader("Utility & info")
    st.write("Base currency:", base)
    st.write("Target currency:", target)
    # show names
    st.write("Base name:", symbols.get(base, {}).get("description", ""))
    st.write("Target name:", symbols.get(target, {}).get("description", ""))

# Right column: charts & analytics
with col2:
    st.subheader("Analytics & Visuals")
    # manual refresh handling
    if refresh_btn:
        # clear caches by re-calling fetch functions with different args; streamlit cache_data TTL will handle
        st.success("Refreshing cached rates...")
    # show top10 bar
    if show_top10:
        st.markdown("### Top currencies comparison")
        try:
            plot_top10_rates(base, symbols)
        except Exception as e:
            st.error("Failed to load top-10 chart: " + str(e))

    # historical timeseries
    st.markdown("### Historical trend for selected pair")
    days = 7 if days_history == "7 days" else 30 if days_history == "30 days" else 90
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    try:
        ts_df = fetch_timeseries(base, target, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        plot_timeseries(ts_df, base, target)
    except Exception as e:
        st.error("Could not fetch historical data: " + str(e))

    # pie chart
    if show_pie:
        st.markdown("### Pie / distribution")
        try:
            plot_pie_distribution(base, symbols)
        except Exception as e:
            st.error("Pie chart failed: " + str(e))

# Footer: additional features
st.markdown("---")
st.markdown("### Extra features & tips")
st.markdown("""
- Natural language input: `convert 500 USD to PKR` tries to auto-detect amounts & currency codes.  
- If a currency is missing, please search for its 3-letter ISO code (e.g., `USD`, `EUR`, `PKR`).  
- Use the **sidebar** to change options like auto-refresh and history range.  
""")

st.markdown("Made with ❤️ · Data: exchangerate.host (free, no API key).")

# End of app
