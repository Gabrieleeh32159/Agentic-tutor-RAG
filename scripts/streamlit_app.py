"""Internal dev tool: exercises the session + upload + chat SSE API.

The real user-facing UI is the Next.js app in /web (Phase 6).
Run with:
    uv run streamlit run scripts/streamlit_app.py
"""

from __future__ import annotations

import json

import httpx
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Ask your PDFs (dev)", page_icon="📄", layout="wide")
st.title("📄 Ask your PDFs — dev tool")

# ---------------------------------------------------------------------------
# Sidebar: session + documents
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Session")

    if st.button("➕ New session"):
        try:
            resp = httpx.post(f"{API_URL}/sessions", timeout=10.0)
            resp.raise_for_status()
            st.session_state["session_id"] = resp.json()["id"]
            st.session_state["messages"] = []
            st.rerun()
        except httpx.HTTPError as exc:
            st.error(f"Cannot create session: {exc}")

    session_id = st.session_state.get("session_id")
    if not session_id:
        st.info("Create a session to begin.")
    else:
        st.caption(f"Session: `{session_id}`")

        uploaded = st.file_uploader(
            "Upload a document (.txt / .md)", type=["txt", "md"]
        )
        if uploaded is not None and st.button("Ingest file"):
            resp = httpx.post(
                f"{API_URL}/sessions/{session_id}/documents",
                files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                timeout=120.0,
            )
            if resp.status_code == 202:
                st.success(f"{uploaded.name}: {resp.json()['status']}")
            else:
                st.error(f"{resp.status_code}: {resp.text}")

        st.divider()
        st.subheader("Documents")
        try:
            docs = httpx.get(
                f"{API_URL}/sessions/{session_id}/documents", timeout=10.0
            ).json()
            if isinstance(docs, list):
                for doc in docs:
                    icon = {"ready": "✅", "failed": "❌"}.get(doc["status"], "⏳")
                    st.write(f"{icon} {doc['filename']} ({doc['chunk_count']} chunks)")
            else:
                st.warning(docs)
        except httpx.HTTPError:
            st.warning(f"Cannot reach API at {API_URL}")

        st.divider()
        if st.button("🗑️ Delete session"):
            httpx.delete(f"{API_URL}/sessions/{session_id}", timeout=10.0)
            st.session_state.pop("session_id", None)
            st.session_state["messages"] = []
            st.rerun()

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("Ask about your documents…"):
    if not st.session_state.get("session_id"):
        st.error("Create a session first.")
        st.stop()

    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    payload = {
        "question": question,
        "session_id": st.session_state["session_id"],
    }

    with st.chat_message("assistant"):
        flow_container = st.container()
        answer_placeholder = st.empty()
        answer_tokens: list[str] = []
        current_answer = ""

        try:
            with httpx.stream(
                "POST", f"{API_URL}/chat", json=payload, timeout=120.0
            ) as response:
                if response.status_code != 200:
                    response.read()
                    st.error(f"API error {response.status_code}: {response.text}")
                else:
                    for line in response.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ")
                        if data == "[DONE]":
                            break

                        parsed = json.loads(data)

                        if "sources" in parsed:
                            sources = parsed["sources"]
                            with (
                                flow_container,
                                st.expander(f"📚 Retrieved {len(sources)} documents"),
                            ):
                                for src in sources:
                                    st.markdown(
                                        f"**{src['filename']}** — "
                                        f"score {src['score'] * 100:.1f}%"
                                    )
                                    for chunk in src.get("chunks", [])[:3]:
                                        st.caption(
                                            f"↳ ({chunk['score']:.4f}) "
                                            f"{chunk['chunk_text'][:200]}…"
                                        )
                        elif "step" in parsed:
                            with flow_container:
                                st.info(f"{parsed['step']}: {parsed.get('detail', '')}")
                        elif "token" in parsed:
                            answer_tokens.append(parsed["token"])
                            current_answer = "".join(answer_tokens)
                            answer_placeholder.markdown(current_answer + "▌")
                        elif "error" in parsed:
                            st.error(f"Error: {parsed['error']}")

            if current_answer:
                answer_placeholder.markdown(current_answer)

        except httpx.ConnectError:
            st.error(
                f"Cannot connect to {API_URL}. "
                "Start the API: `uv run fastapi dev app/main.py`"
            )

    if current_answer:
        st.session_state["messages"].append(
            {"role": "assistant", "content": current_answer}
        )
