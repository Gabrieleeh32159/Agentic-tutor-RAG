from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.chat.models import AgentState, NodeName
from app.chat.prompts import SYSTEM_PROMPT
from app.chat.repository import (
    get_session_messages,
    load_session_messages,
    save_messages,
)
from app.chat.tools import make_search_tool
from app.shared.llm import get_chat_model

logger = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_PROMPT",
    "build_graph",
    "get_session_messages",
    "load_session_messages",
    "save_messages",
]

# ---------------------------------------------------------------------------
# Agent graph
# ---------------------------------------------------------------------------


def _make_agent_node(llm_with_tools: BaseChatModel):
    async def agent(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        messages = state.get("messages", [])
        tagged_config = {**config, "tags": [*(config.get("tags") or []), "agent_llm"]}
        full_response = None
        async for chunk in llm_with_tools.astream(messages, config=tagged_config):
            if full_response is None:
                full_response = chunk
            else:
                full_response += chunk
        return {"messages": [full_response]}

    return agent


def build_graph(
    http_client: httpx.AsyncClient,
    llm: BaseChatModel | None = None,
):
    if llm is None:
        llm = get_chat_model()

    search_tool = make_search_tool(http_client, llm)
    llm_with_tools = llm.bind_tools([search_tool])

    workflow = StateGraph(AgentState)

    workflow.add_node(NodeName.AGENT, _make_agent_node(llm_with_tools))
    workflow.add_node(NodeName.TOOLS, ToolNode([search_tool]))

    workflow.set_entry_point(NodeName.AGENT)
    workflow.add_conditional_edges(
        NodeName.AGENT,
        tools_condition,
        {NodeName.TOOLS: NodeName.TOOLS, END: END},
    )
    workflow.add_edge(NodeName.TOOLS, NodeName.AGENT)

    return workflow.compile()
