"""LangGraph orchestration for the cart-recovery flow.

Two interaction surfaces:

1. `build_graph()` -- a compiled `StateGraph` encoding the trigger path:
       trigger_listener -> intent_classifier -> policy_rag_retriever
       -> offer_generator -> guardrail_check
       -> (pass)    checkout_relink -> outcome_logger -> END
       -> (fail<max) offer_generator          # regenerate
       -> (fail>=max) escalate   -> outcome_logger -> END
   The guardrail retry counter (`offer_attempts`) bounds the regenerate loop
   so a hallucinating model can never spin forever.

2. `run_negotiation(state, message)` -- the resume path used by POST /chat.
   A customer reply arrives AFTER the trigger flow has ended (the graph
   terminated at `outcome_logger`). Rather than stand up a checkpointer +
   interrupt protocol for a hackathon, we orchestrate the *same* node
   functions imperatively here -- appending the user message, bumping
   `negotiation_turns`, and routing to escalation vs. offer regeneration.
   The `negotiation_turns >= MAX_NEGOTIATION_TURNS -> escalate` rule is
   enforced on this path. The chat_history append-reducer is applied by
   hand via `_merge` since we bypass the compiled graph.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.nodes.checkout_relink import checkout_relink
from app.agents.nodes.escalate import escalate_to_human_node
from app.agents.nodes.guardrail_check import guardrail_check
from app.agents.nodes.intent_classifier import intent_classifier
from app.agents.nodes.negotiation import INBOUND_KEY, negotiation_node
from app.agents.nodes.offer_generator import offer_generator
from app.agents.nodes.outcome_logger import outcome_logger
from app.agents.nodes.policy_rag_retriever import policy_rag_retriever
from app.agents.nodes.trigger_listener import trigger_listener
from app.config import get_settings
from app.state import RecoveryState

logger = logging.getLogger(__name__)


# --- routers --------------------------------------------------------------

def _guardrail_router(state: RecoveryState) -> str:
    g = state.get("guardrail") or {}
    if g.get("passed"):
        return "checkout_relink"
    if (state.get("offer_attempts") or 0) >= get_settings().max_guardrail_retries:
        return "escalate"
    return "offer_generator"


def _negotiation_router(state: RecoveryState) -> str:
    if (state.get("negotiation_turns") or 0) >= get_settings().max_negotiation_turns:
        return "escalate"
    return "offer_generator"


def build_graph():
    """Compile and return the recovery StateGraph (trigger path)."""
    g: StateGraph = StateGraph(RecoveryState)
    g.add_node("trigger_listener", trigger_listener)
    g.add_node("intent_classifier", intent_classifier)
    g.add_node("policy_rag_retriever", policy_rag_retriever)
    g.add_node("offer_generator", offer_generator)
    g.add_node("guardrail_check", guardrail_check)
    g.add_node("negotiation_node", negotiation_node)
    g.add_node("checkout_relink", checkout_relink)
    g.add_node("escalate", escalate_to_human_node)
    g.add_node("outcome_logger", outcome_logger)

    g.set_entry_point("trigger_listener")
    g.add_edge("trigger_listener", "intent_classifier")
    g.add_edge("intent_classifier", "policy_rag_retriever")
    g.add_edge("policy_rag_retriever", "offer_generator")
    g.add_edge("offer_generator", "guardrail_check")
    g.add_conditional_edges(
        "guardrail_check",
        _guardrail_router,
        {"checkout_relink": "checkout_relink",
         "offer_generator": "offer_generator",
         "escalate": "escalate"},
    )
    g.add_edge("checkout_relink", "outcome_logger")
    # negotiation_node is entered on customer reply (see run_negotiation);
    # its conditional edge encodes the turns>=max -> escalate rule.
    g.add_conditional_edges(
        "negotiation_node",
        _negotiation_router,
        {"escalate": "escalate", "offer_generator": "offer_generator"},
    )
    g.add_edge("escalate", "outcome_logger")
    g.add_edge("outcome_logger", END)
    return g.compile()


# Shared compiled graph (stateless across sessions -- state lives in Redis/Postgres).
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


# --- imperative resume path (POST /chat) ----------------------------------

ACCEPT_HINTS = {"yes", "ok", "okay", "sure", "accept", "accepted", "buy", "proceed", "go ahead", "take it", "deal"}
DECLINE_HINTS = {"no", "cancel", "stop", "refuse", "declined", "don't want", "dont want", "not interested", "opt out"}


def _matches_hints(text: str, hints: set[str]) -> bool:
    """Match hints with word-boundary awareness -- avoids substring false
    positives like 'no' matching inside 'ignore'."""
    text_lower = text.lower()
    for h in hints:
        if re.search(r"\b" + re.escape(h) + r"\b", text_lower):
            return True
    return False


def _merge(state: dict[str, Any], delta: dict[str, Any]) -> None:
    """Apply a node's partial delta, honouring the chat_history append reducer."""
    for k, v in delta.items():
        if k == "chat_history":
            state["chat_history"] = (state.get("chat_history") or []) + (v or [])
        else:
            state[k] = v


async def run_negotiation(state: RecoveryState, user_message: str) -> RecoveryState:
    """Resume a session on a customer reply.

    Sequence:
      negotiation_node (append msg + bump turns)
      -> if turns>=max: escalate -> outcome_logger -> return
      -> if accepts:    checkout_relink -> outcome_logger -> return
      -> if declines:  outcome="abandoned" -> outcome_logger -> return
      -> else:          offer_generator -> guardrail (retry to cap)
                        -> pass: return (offer shown)
                        -> fail after cap: escalate -> outcome_logger
    """
    settings = get_settings()
    state = {**state, INBOUND_KEY: user_message}

    delta = await negotiation_node(state)
    _merge(state, delta)

    turns = state.get("negotiation_turns") or 0
    lowered = (user_message or "").lower().strip()
    accepts = _matches_hints(user_message, ACCEPT_HINTS)
    declines = _matches_hints(user_message, DECLINE_HINTS)

    if turns >= settings.max_negotiation_turns:
        delta = await escalate_to_human_node(state); _merge(state, delta)
        delta = await outcome_logger(state); _merge(state, delta)
        return state

    if accepts:
        delta = await checkout_relink(state); _merge(state, delta)
        delta = await outcome_logger(state); _merge(state, delta)
        return state

    if declines:
        state["outcome"] = "abandoned"
        delta = await outcome_logger(state); _merge(state, delta)
        return state

    # Regenerate an offer through the guardrail (bounded retries).
    for _ in range(settings.max_guardrail_retries):
        delta = await offer_generator(state); _merge(state, delta)
        delta = await guardrail_check(state); _merge(state, delta)
        if (state.get("guardrail") or {}).get("passed"):
            break

    if not (state.get("guardrail") or {}).get("passed"):
        delta = await escalate_to_human_node(state); _merge(state, delta)

    delta = await outcome_logger(state); _merge(state, delta)
    return state
