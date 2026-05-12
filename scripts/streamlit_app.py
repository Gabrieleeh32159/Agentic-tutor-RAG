"""Streamlit chat UI that visualises the full agentic RAG flow.

Run with:
    uv run streamlit run scripts/streamlit_app.py
"""

from __future__ import annotations

import json

import httpx
import streamlit as st

API_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="📚 Study Assistant", page_icon="📚", layout="wide")
st.title("📚 Study Assistant")

# ---------------------------------------------------------------------------
# Sidebar – session management + filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Settings")

    subject = st.text_input("Subject filter (optional)", placeholder="e.g. math, biology")
    level = st.selectbox(
        "Level filter (optional)",
        options=["", "introductory", "intermediate", "advanced"],
        index=0,
    )

    st.divider()
    st.header("💬 Sessions")

    if st.button("➕ New session"):
        st.session_state.pop("session_id", None)
        st.session_state["messages"] = []
        st.session_state["flow_events"] = []
        st.rerun()

    # Fetch existing sessions
    try:
        sessions_resp = httpx.get(f"{API_URL}/chat/sessions", timeout=5.0)
        if sessions_resp.status_code == 200:
            sessions = sessions_resp.json()
            for s in sessions:
                label = s.get("title") or "Untitled"
                sid = s["id"]
                if st.button(f"📝 {label[:40]}", key=f"sess_{sid}"):
                    st.session_state["session_id"] = sid
                    st.session_state["messages"] = []
                    st.session_state["flow_events"] = []
                    # Load history
                    msgs_resp = httpx.get(
                        f"{API_URL}/chat/sessions/{sid}/messages", timeout=5.0
                    )
                    if msgs_resp.status_code == 200:
                        for m in msgs_resp.json():
                            if m["role"] == "human":
                                st.session_state["messages"].append(
                                    {"role": "user", "content": m["content"]}
                                )
                            elif m["role"] == "ai" and m["content"]:
                                st.session_state["messages"].append(
                                    {"role": "assistant", "content": m["content"]}
                                )
                    st.rerun()
    except httpx.ConnectError:
        st.warning("⚠️ Cannot connect to API at " + API_URL)

    st.divider()
    if "session_id" in st.session_state:
        if st.button("🗑️ Delete current session"):
            httpx.delete(
                f"{API_URL}/chat/sessions/{st.session_state['session_id']}",
                timeout=5.0,
            )
            st.session_state.pop("session_id", None)
            st.session_state["messages"] = []
            st.session_state["flow_events"] = []
            st.rerun()

# ---------------------------------------------------------------------------
# Initialise state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "flow_events" not in st.session_state:
    st.session_state["flow_events"] = []

# ---------------------------------------------------------------------------
# Render chat history
# ---------------------------------------------------------------------------

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

if question := st.chat_input("Ask a question…"):
    # Display user message
    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Build payload
    payload: dict[str, str] = {"question": question}
    if st.session_state.get("session_id"):
        payload["session_id"] = st.session_state["session_id"]
    if subject:
        payload["subject"] = subject
    if level:
        payload["level"] = level

    # Stream response
    with st.chat_message("assistant"):
        flow_container = st.container()
        answer_placeholder = st.empty()

        flow_events: list[dict] = []
        answer_tokens: list[str] = []
        current_answer = ""

        try:
            with httpx.stream(
                "POST", f"{API_URL}/chat", json=payload, timeout=120.0
            ) as response:
                if response.status_code != 200:
                    st.error(f"API error: {response.status_code}")
                else:
                    for line in response.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ")
                        if data == "[DONE]":
                            break

                        parsed = json.loads(data)

                        # --- Session ID ---
                        if "session_id" in parsed:
                            st.session_state["session_id"] = parsed["session_id"]

                        # --- Sources ---
                        elif "sources" in parsed:
                            sources = parsed["sources"]
                            event = {"type": "sources", "sources": sources}
                            flow_events.append(event)
                            with flow_container:
                                with st.expander(
                                    f"📚 Retrieved {len(sources)} documents",
                                    expanded=False,
                                ):
                                    for src in sources:
                                        score_pct = src["score"] * 100
                                        st.markdown(
                                            f"**{src['title']}** — "
                                            f"Score: {score_pct:.1f}%"
                                        )
                                        chunks = src.get("chunks", [])
                                        for chunk in chunks[:3]:
                                            preview = chunk["chunk_text"][:200]
                                            st.caption(
                                                f"  ↳ (score {chunk['score']:.4f}) "
                                                f"{preview}…"
                                            )

                        # --- Steps ---
                        elif "step" in parsed:
                            step = parsed["step"]
                            flow_events.append(parsed)

                            with flow_container:
                                if step == "retrieve":
                                    st.info(
                                        f"🔍 {parsed.get('detail', '')}",
                                        icon="🔍",
                                    )
                                elif step == "grade_documents":
                                    is_rel = parsed.get("is_relevant", False)
                                    query = parsed.get("query", "")
                                    if is_rel:
                                        st.success(
                                            f'✅ Results for "{query}" are relevant',
                                            icon="✅",
                                        )
                                    else:
                                        st.warning(
                                            f'❌ Results for "{query}" are not relevant',
                                            icon="❌",
                                        )
                                elif step == "rewrite_query":
                                    new_q = parsed.get("new_question", "")
                                    attempt = parsed.get("retry", 0)
                                    st.info(
                                        f'🔄 Rewriting query (attempt {attempt}): "{new_q}"',
                                        icon="🔄",
                                    )

                        # --- Tokens ---
                        elif "token" in parsed:
                            answer_tokens.append(parsed["token"])
                            current_answer = "".join(answer_tokens)
                            answer_placeholder.markdown(current_answer + "▌")

                        # --- Errors ---
                        elif "error" in parsed:
                            st.error(f"Error: {parsed['error']}")

            # Finalise answer
            if current_answer:
                answer_placeholder.markdown(current_answer)

        except httpx.ConnectError:
            st.error(
                f"Cannot connect to {API_URL}. "
                "Make sure the API is running: `uv run fastapi dev app/main.py`"
            )

    # Save to state
    if current_answer:
        st.session_state["messages"].append(
            {"role": "assistant", "content": current_answer}
        )
    st.session_state["flow_events"].extend(flow_events)
