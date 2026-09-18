"""
Company Research Assistant - Streamlit app.

Single-page, ChatGPT-style UI: type a company name or website URL, watch
live progress, get an AI-generated research report with competitor
analysis, download it as a PDF, and optionally push it straight to Discord.
"""

import os

import streamlit as st

from utils import (
    DEFAULT_MODELS,
    generate_pdf,
    run_research,
    send_to_discord,
)

st.set_page_config(page_title="Company Research Assistant", page_icon="🔎", layout="centered")


def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


SERPER_API_KEY = get_secret("SERPER_API_KEY")
OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")
DEFAULT_MODEL = get_secret("OPENROUTER_DEFAULT_MODEL", DEFAULT_MODELS[0])

if "messages" not in st.session_state:
    st.session_state.messages = []  # each: {"role": "user"/"assistant", ...}
if "discord_config" not in st.session_state:
    st.session_state.discord_config = {
        "bot_token": "", "channel_id": "", "applicant_name": "", "applicant_email": "",
    }

# --------------------------------------------------------------------------
# Sidebar: model + Discord settings
# --------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚙️ Settings")

    model_options = DEFAULT_MODELS + ["Custom..."]
    default_index = model_options.index(DEFAULT_MODEL) if DEFAULT_MODEL in model_options else 0
    chosen = st.selectbox("AI model (OpenRouter)", model_options, index=default_index)
    if chosen == "Custom...":
        model = st.text_input("Custom OpenRouter model slug", value=DEFAULT_MODEL)
    else:
        model = chosen

    if not SERPER_API_KEY or not OPENROUTER_API_KEY:
        st.warning("Add `SERPER_API_KEY` and `OPENROUTER_API_KEY` to `.streamlit/secrets.toml` (or env vars) before researching.")

    st.markdown("---")
    st.markdown("### 💬 Discord Integration")
    st.caption("Stored only for this session — no database.")
    cfg = st.session_state.discord_config
    cfg["bot_token"] = st.text_input("Discord Bot Token", value=cfg["bot_token"], type="password")
    cfg["channel_id"] = st.text_input("Discord Channel ID", value=cfg["channel_id"])
    cfg["applicant_name"] = st.text_input("Applicant Name", value=cfg["applicant_name"])
    cfg["applicant_email"] = st.text_input("Applicant Email", value=cfg["applicant_email"])

# --------------------------------------------------------------------------
# Render a completed research result
# --------------------------------------------------------------------------

def render_result(result: dict, pdf_bytes: bytes, msg_key: str):
    st.markdown(f"### {result.get('companyName', 'Unknown company')}")
    if result.get("website"):
        st.markdown(f"🔗 [{result['website']}]({result['website']})")

    meta_bits = []
    if result.get("phone"):
        meta_bits.append(f"📞 {result['phone']}")
    if result.get("address"):
        meta_bits.append(f"📍 {result['address']}")
    if meta_bits:
        st.caption(" &nbsp;·&nbsp; ".join(meta_bits))

    if result.get("summary"):
        st.write(result["summary"])

    if result.get("products"):
        st.markdown("**Products / Services**")
        for p in result["products"]:
            st.markdown(f"- {p}")

    if result.get("painPoints"):
        st.markdown("**AI-Generated Pain Points**")
        for p in result["painPoints"]:
            st.markdown(f"- {p}")

    competitors = result.get("competitors") or []
    st.markdown("**Competitors**")
    if competitors:
        st.table([{"Name": c.get("name", ""), "Website": c.get("website", "")} for c in competitors])
    else:
        st.caption("No competitors could be identified.")

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "⬇ Download PDF report",
            data=pdf_bytes,
            file_name=f"{result.get('companyName', 'company').replace(' ', '-')}-research-report.pdf",
            mime="application/pdf",
            key=f"download_{msg_key}",
        )
    with col2:
        cfg = st.session_state.discord_config
        discord_ready = bool(cfg["bot_token"] and cfg["channel_id"])
        sent_flag = f"discord_sent_{msg_key}"
        if discord_ready:
            already_sent = st.session_state.get(sent_flag, False)
            if st.button("📨 Send to Discord", key=f"discord_btn_{msg_key}", disabled=already_sent):
                try:
                    with st.spinner("Sending to Discord..."):
                        send_to_discord(
                            cfg["bot_token"], cfg["channel_id"],
                            cfg["applicant_name"], cfg["applicant_email"],
                            result, pdf_bytes,
                        )
                    st.session_state[sent_flag] = True
                    st.success("Sent to Discord ✓")
                except Exception as e:
                    st.error(f"Failed to send to Discord: {e}")
            elif already_sent:
                st.success("Sent to Discord ✓")
        else:
            st.caption("Configure Discord in the sidebar to enable sending.")

    st.caption(f"Model: {result.get('model', '')} · Generated {result.get('generatedAt', '')}")


# --------------------------------------------------------------------------
# Main chat area
# --------------------------------------------------------------------------

st.markdown("## 🔎 Company Research Assistant")
st.caption("AI-powered research · website crawling · competitor analysis · PDF reports")

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["content"])
        elif msg.get("error"):
            st.error(msg["error"])
        elif msg.get("result"):
            render_result(msg["result"], msg["pdf_bytes"], msg_key=str(i))

query = st.chat_input("Enter a company name (e.g. Stripe) or a website URL (e.g. https://stripe.com)...")

if query:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.write(query)

    with st.chat_message("assistant"):
        status_box = st.status("Starting research...", expanded=True)

        def on_status(message: str):
            status_box.write(message)

        try:
            result = run_research(
                query=query,
                model=model,
                serper_key=SERPER_API_KEY,
                openrouter_key=OPENROUTER_API_KEY,
                status_callback=on_status,
            )
            status_box.update(label="Research complete", state="complete", expanded=False)
            pdf_bytes = generate_pdf(result)
            render_result(result, pdf_bytes, msg_key=str(len(st.session_state.messages)))
            st.session_state.messages.append({
                "role": "assistant", "result": result, "pdf_bytes": pdf_bytes,
            })
        except Exception as e:
            status_box.update(label="Research failed", state="error", expanded=False)
            st.error(str(e))
            st.session_state.messages.append({"role": "assistant", "error": str(e)})
