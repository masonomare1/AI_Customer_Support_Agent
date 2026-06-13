"""LangGraph agent for e-commerce refund decisions."""

import json
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.tools import ALL_TOOLS, TOOL_BY_NAME
from ws_manager import manager

SYSTEM_PROMPT = """You are an AI customer support agent for an e-commerce refund desk.
You handle two kinds of messages:

A) GENERAL QUESTIONS — e.g. "what is your refund policy?", "how long do I have to
   return something?", "do you refund final-sale items?". Answer these directly and
   helpfully. If the question is about the policy, call get_refund_policy to read it,
   then SUMMARIZE the relevant parts back to the customer in plain language. Do NOT
   ask for an order ID unless the customer actually wants to start a refund.

B) REFUND REQUESTS — evaluate fairly and strictly according to company policy.

WHAT THE CUSTOMER CAN SEE (very important):
The customer ONLY reads your final written reply. They CANNOT see your tool calls or
tool results. Never say things like "the policy has been provided to you" or refer to
information the customer cannot see. Whatever the customer asked for — the policy text,
the decision, the reason, the amount — must appear IN your reply.

REFUND WORKFLOW (for refund requests only):
1. ALWAYS use tools to verify facts before any decision — never guess.
2. You MUST call check_refund_eligibility AND check_refund_history before deciding.
3. Use lookup_customer / lookup_order for context. If no order ID was given, ask for it.
4. To APPROVE: call calculate_refund_amount, then process_refund with decision="approved".
5. To DENY: call process_refund with amount=0 and decision="denied".
6. process_refund is the authoritative policy engine. If you try to approve a refund that
   breaks a hard rule (an order refunded twice, or a second refund inside the 30-day
   window) it will BLOCK the approval and record a denial. Trust its result: if it returns
   "blocked", tell the customer the refund is DENIED and explain that rule.

WRITING YOUR FINAL REPLY for a refund decision — be explicit and give reasons:
- Start with "✅ Refund Approved" or "❌ Refund Denied".
- Name the specific policy rule that applied (e.g. "defective item within 90 days",
  "30-day change-of-mind window with 15% restocking fee", "one approved refund per
  30 days", "final-sale items are non-refundable").
- If approved: state the refund amount and any restocking fee.
- If denied: clearly and empathetically explain why.
Keep it concise. Do not output internal tags, codes, or raw tool output."""


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    customer_id: str
    reasoning_steps: List[dict]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _emit(step_type: str, payload: Dict[str, Any], customer_id: str) -> None:
    event = {
        "type": step_type,
        "timestamp": _now_iso(),
        "customer_id": customer_id,
        **payload,
    }
    await manager.broadcast(event)


def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=api_key,
        temperature=0.2,
    )


async def agent_node(state: AgentState) -> Dict[str, Any]:
    llm = _get_llm().bind_tools(ALL_TOOLS)
    response = await llm.ainvoke(state["messages"])

    if response.content:
        await _emit(
            "thought",
            {"content": response.content},
            state["customer_id"],
        )

    return {"messages": [response]}


async def tool_node(state: AgentState) -> Dict[str, Any]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}

    tool_messages: List[ToolMessage] = []
    reasoning_steps = list(state.get("reasoning_steps", []))

    for tool_call in last_message.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]
        tool_id = tool_call["id"]

        await _emit(
            "tool_call",
            {"tool": name, "input": args},
            state["customer_id"],
        )

        tool_fn = TOOL_BY_NAME.get(name)
        if tool_fn is None:
            result = {"error": f"Unknown tool: {name}"}
        else:
            try:
                result = tool_fn.invoke(args)
            except Exception as exc:
                result = {"error": str(exc)}

        if not isinstance(result, str):
            result_str = json.dumps(result, default=str)
        else:
            result_str = result

        await _emit(
            "tool_result",
            {"tool": name, "output": result},
            state["customer_id"],
        )

        step = {
            "type": "tool_result",
            "tool": name,
            "input": args,
            "output": result,
        }
        reasoning_steps.append(step)
        tool_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id, name=name))

    return {"messages": tool_messages, "reasoning_steps": reasoning_steps}


def _route_after_agent(state: AgentState) -> Literal["tools", "end"]:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"


def _decision_from_steps(reasoning_steps: List[dict]) -> str:
    """Authoritative decision: read the last process_refund tool result."""
    for step in reversed(reasoning_steps):
        if step.get("tool") != "process_refund":
            continue
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("blocked"):
            return "deny_refund"
        decision = str(output.get("decision", "")).lower()
        if decision == "approved":
            return "approve_refund"
        if decision == "denied":
            return "deny_refund"
    return "unknown"


def _extract_decision(text: str) -> str:
    """Fallback: infer decision from the reply text if no process_refund call ran."""
    text_lower = text.lower()
    if "refund approved" in text_lower or "approve_refund" in text_lower:
        return "approve_refund"
    if "refund denied" in text_lower or "deny_refund" in text_lower:
        return "deny_refund"
    return "unknown"


def _clean_reply(text: str) -> str:
    """Strip any internal DECISION: tag the model might still emit."""
    lines = [ln for ln in text.splitlines() if not ln.strip().lower().startswith("decision:")]
    return "\n".join(lines).strip()


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")
    return graph.compile()


async def run_agent(customer_id: str, message: str) -> Dict[str, Any]:
    graph = build_graph()
    initial_messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=f"Customer ID: {customer_id}\n\nCustomer message:\n{message}"
        ),
    ]

    result = await graph.ainvoke(
        {
            "messages": initial_messages,
            "customer_id": customer_id,
            "reasoning_steps": [],
        }
    )

    final_text = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    final_text = _clean_reply(final_text)

    reasoning_steps = result.get("reasoning_steps", [])
    decision = _decision_from_steps(reasoning_steps)
    if decision == "unknown":
        decision = _extract_decision(final_text)

    await _emit(
        "decision",
        {"decision": decision, "response": final_text},
        customer_id,
    )

    return {
        "response": final_text,
        "decision": decision,
        "customer_id": customer_id,
        "reasoning_steps": reasoning_steps,
    }
