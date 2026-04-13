"""
Extraction Graph
================

LangGraph StateGraph for the Extraction phase (Phase 2).
Orchestrates Planner, Extractor, Critic, and Normalizer agents.

CRITICAL INVARIANTS:
1. Every subagent gets FULL paper_content_text (~10-50KB, NEVER truncate)
2. Each agent has access to ONLY its designated tools
3. Iteration loop: Critic → Extractor (max 3 iterations)
4. State accumulates across all agents
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from .state import ExtractionGraphState
from .prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    PLANNER_PROMPT,
    EXTRACTOR_PROMPT,
    CRITIC_PROMPT,
    NORMALIZER_PROMPT,
)
from runtime.llm import (
    get_planner_llm,
    get_extractor_llm,
    get_critic_llm,
    get_normalizer_llm,
)
from tools.tool_registry import (
    get_planner_tools,
    get_extractor_tools,
    get_critic_tools,
    get_normalizer_tools,
)
from tools.context import set_context, get_context, ToolContext

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _parse_xml_tool_calls(content: str) -> List[Dict[str, Any]]:
    """
    Parse XML-style tool calls from GLM-4 model output.

    GLM-4 outputs tool calls in format:
    <tool_call>tool_name</tool_call>
    or
    <tool_call>tool_name(arg1="value1", arg2="value2")</tool_call>
    or
    <tool_call>{"name": "tool_name", "arguments": {...}}</tool_call>

    Args:
        content: The LLM response content

    Returns:
        List of parsed tool calls with name, args, and generated id
    """
    if not content:
        return []

    tool_calls = []

    # Pattern 1: <tool_call>tool_name</tool_call> or <tool_call>tool_name(args)</tool_call>
    pattern1 = re.compile(r'<tool_call>\s*(\w+)(?:\((.*?)\))?\s*</tool_call>', re.DOTALL)
    for match in pattern1.finditer(content):
        tool_name = match.group(1)
        args_str = match.group(2) or ""

        # Parse arguments
        args = {}
        if args_str:
            # Try to parse as key=value pairs
            arg_pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\{.*?\})|(\[.*?\])|([^,\)]+))')
            for arg_match in arg_pattern.finditer(args_str):
                key = arg_match.group(1)
                # Get the value from whichever group matched
                value = arg_match.group(2) or arg_match.group(3) or arg_match.group(4) or arg_match.group(5) or arg_match.group(6)
                if value:
                    value = value.strip()
                    # Try to parse JSON values
                    if value.startswith('{') or value.startswith('['):
                        try:
                            value = json.loads(value)
                        except:
                            pass
                    args[key] = value

        tool_calls.append({
            "name": tool_name,
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:8]}"
        })

    # Pattern 2: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    pattern2 = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)
    for match in pattern2.finditer(content):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "name" in data:
                tool_calls.append({
                    "name": data["name"],
                    "args": data.get("arguments", data.get("args", {})),
                    "id": f"call_{uuid.uuid4().hex[:8]}"
                })
        except json.JSONDecodeError:
            pass

    # Pattern 3: Function call notation like save_extraction_plan(paper_type="...", ...)
    pattern3 = re.compile(r'(?<![<\w])(\w+)\(\s*([^)]*)\s*\)(?![>])', re.DOTALL)
    tool_names_found = {tc["name"] for tc in tool_calls}  # Avoid duplicates
    for match in pattern3.finditer(content):
        tool_name = match.group(1)
        # Skip common words that aren't tool calls
        if tool_name in tool_names_found or tool_name in ['if', 'for', 'while', 'print', 'len', 'str', 'int', 'dict', 'list', 'range']:
            continue

        args_str = match.group(2) or ""
        args = {}

        if args_str:
            # Try to parse as key=value pairs
            arg_pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\{.*?\})|(\[.*?\])|([^,]+))')
            for arg_match in arg_pattern.finditer(args_str):
                key = arg_match.group(1)
                value = arg_match.group(2) or arg_match.group(3) or arg_match.group(4) or arg_match.group(5) or arg_match.group(6)
                if value:
                    value = value.strip()
                    if value.startswith('{') or value.startswith('['):
                        try:
                            value = json.loads(value)
                        except:
                            pass
                    args[key] = value

        # Only add if it looks like a valid tool call (has underscore or is known tool)
        if '_' in tool_name or tool_name in ['get', 'save', 'check', 'validate', 'lookup', 'increment', 'finalize']:
            tool_calls.append({
                "name": tool_name,
                "args": args,
                "id": f"call_{uuid.uuid4().hex[:8]}"
            })

    return tool_calls


def _setup_context_from_state(state: ExtractionGraphState) -> ToolContext:
    """Set up tool context from graph state."""
    ctx = ToolContext()
    ctx.paper_id = state.get("paper_id", "")
    ctx.paper_content = state.get("paper_content", {})
    ctx.paper_content_text = state.get("paper_content_text", "")
    ctx.extraction_plan = state.get("extraction_plan", {})
    ctx.draft_extractions = state.get("draft_extractions", [])
    ctx.critique = state.get("critique", {})
    ctx.iteration_count = state.get("iteration_count", 0)
    ctx.max_iterations = state.get("max_iterations", 3)
    ctx.paper_type = state.get("paper_type", "")
    ctx.author = state.get("author", "")
    ctx.year = state.get("year", "")
    set_context(ctx)
    return ctx


def _run_agent_with_tools(
    system_prompt: str,
    user_prompt: str,
    llm,
    tools: list,
    state: ExtractionGraphState,
    agent_name: str,
) -> Dict[str, Any]:
    """
    Run an agent with tool execution loop.

    Args:
        system_prompt: System prompt for the agent
        user_prompt: User message to start the agent
        llm: LLM instance
        tools: List of tools available to the agent
        state: Current graph state
        agent_name: Name of the agent for logging

    Returns:
        Dict with updated state fields
    """
    logger.info(f"=== {agent_name.upper()} NODE START ===")

    # Set up context
    _setup_context_from_state(state)

    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)

    # Build messages
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]

    # Tool execution loop
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"{agent_name} iteration {iteration}")

        # Call LLM
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # Get tool calls - first try native, then parse XML from content
        tool_calls_to_execute = response.tool_calls if response.tool_calls else []

        # If no native tool calls, try parsing XML-style calls from content
        if not tool_calls_to_execute and response.content:
            parsed_calls = _parse_xml_tool_calls(response.content)
            if parsed_calls:
                logger.info(f"{agent_name} parsed {len(parsed_calls)} XML tool calls from content")
                tool_calls_to_execute = parsed_calls

                # FIX: Synthesize proper AIMessage with tool_calls to maintain protocol
                # Replace the text-only response in messages with one that has proper tool_calls
                messages.pop()  # Remove the text-only AIMessage
                synthesized_response = AIMessage(
                    content=response.content,
                    tool_calls=parsed_calls  # Add the parsed tool calls
                )
                messages.append(synthesized_response)
                logger.info(f"{agent_name}: Synthesized AIMessage with tool_calls for protocol compliance")

        # Check for tool calls
        if not tool_calls_to_execute:
            logger.info(f"{agent_name} completed without more tool calls")
            # Debug: log response content to understand what model is outputting
            if response.content:
                # Log to file for debugging
                import os
                debug_dir = os.path.dirname(os.path.dirname(__file__)) + "/test"
                os.makedirs(debug_dir, exist_ok=True)
                debug_file = f"{debug_dir}/debug_{agent_name}_response.txt"
                with open(debug_file, "w") as f:
                    f.write(f"=== {agent_name} Final Response ===\n")
                    f.write(f"Content length: {len(response.content)}\n\n")
                    f.write(response.content)
                logger.info(f"{agent_name} response saved to {debug_file}")
            break

        # Execute tools
        for tool_call in tool_calls_to_execute:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            logger.info(f"{agent_name} calling tool: {tool_name}")

            # Find and execute tool
            tool = next((t for t in tools if t.name == tool_name), None)
            if tool:
                try:
                    result = tool.invoke(tool_args)
                    messages.append(ToolMessage(
                        content=result if isinstance(result, str) else json.dumps(result),
                        tool_call_id=tool_id
                    ))
                    logger.info(f"Tool {tool_name} completed")
                except Exception as e:
                    error_msg = f"Tool {tool_name} failed: {str(e)}"
                    logger.error(error_msg)
                    messages.append(ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_id
                    ))
            else:
                error_msg = f"Unknown tool: {tool_name}"
                logger.error(error_msg)
                messages.append(ToolMessage(
                    content=error_msg,
                    tool_call_id=tool_id
                ))

    # Get results from context
    ctx = get_context()

    logger.info(f"=== {agent_name.upper()} NODE END ===")

    return {
        "extraction_plan": ctx.extraction_plan,
        "draft_extractions": ctx.draft_extractions,
        "final_extractions": ctx.final_extractions,
        "critique": ctx.critique,
        "iteration_count": ctx.iteration_count,
        "is_complete": ctx.is_complete,
    }


# =============================================================================
# AGENT NODES
# =============================================================================

def planner_node(state: ExtractionGraphState) -> Dict[str, Any]:
    """
    Planner agent: Analyzes paper and creates extraction strategy.
    """
    llm = get_planner_llm()
    tools = get_planner_tools()

    user_prompt = (
        "Analyze the paper content and create an extraction plan. "
        "Call get_paper_content to get the Reader's extraction, "
        "then call save_extraction_plan with your analysis."
    )

    result = _run_agent_with_tools(
        system_prompt=PLANNER_PROMPT,
        user_prompt=user_prompt,
        llm=llm,
        tools=tools,
        state=state,
        agent_name="Planner",
    )
    # If plan wasn't saved, enforce a save pass with tool_choice=save_extraction_plan
    try:
        from tools.context import get_context
        ctx = get_context()
        has_plan = bool(ctx.extraction_plan)
    except Exception:
        has_plan = False

    if not has_plan:
        enforce_prompt = (
            "Finalize the extraction plan now and CALL save_extraction_plan. "
            "Use get_paper_content_json and get_paper_content if needed."
        )
        # Bind tools with tool_choice forcing save_extraction_plan
        llm_required = llm.bind_tools(
            tools,
            tool_choice={"type": "function", "function": {"name": "save_extraction_plan"}},
        )
        messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=enforce_prompt),
        ]
        try:
            resp = llm_required.invoke(messages)
            # No further processing required; tool execution handled in model call
        except Exception as e:
            logger.warning(f"Planner enforcement failed: {e}")

        # Refresh context into result
        try:
            ctx = get_context()
            result.update({"extraction_plan": ctx.extraction_plan})
        except Exception:
            pass

    result["current_phase"] = "planner_complete"
    return result


def extractor_node(state: ExtractionGraphState) -> Dict[str, Any]:
    """
    Extractor agent: Extracts evidence items following the plan.
    """
    llm = get_extractor_llm()
    tools = get_extractor_tools()

    # Check if this is a revision
    iteration = state.get("iteration_count", 0)
    critique = state.get("critique", {})

    if critique and iteration > 0:
        user_prompt = (
            f"This is iteration {iteration + 1}. "
            f"Previous critique feedback: {critique.get('summary', 'No summary')}. "
            "Please revise the extraction based on this feedback. "
            "Call get_paper_content, get_extraction_plan, and get_draft_extractions to see the current state, "
            "then extract improved evidence items and call save_evidence_items."
        )
    else:
        user_prompt = (
            "Extract evidence items from the paper content. "
            "Call get_paper_content to get the full text, "
            "call get_extraction_plan to see the strategy, "
            "then extract evidence items and call save_evidence_items."
        )

    result = _run_agent_with_tools(
        system_prompt=EXTRACTOR_PROMPT,
        user_prompt=user_prompt,
        llm=llm,
        tools=tools,
        state=state,
        agent_name="Extractor",
    )

    result["current_phase"] = "extractor_complete"
    return result


def critic_node(state: ExtractionGraphState) -> Dict[str, Any]:
    """
    Critic agent: Validates extracted evidence items.
    """
    llm = get_critic_llm()
    tools = get_critic_tools()

    user_prompt = (
        "Validate the extracted evidence items against the paper content. "
        "Call get_paper_content, get_extraction_plan, and get_draft_extractions, "
        "then validate each item and call save_critique with your assessment."
    )

    result = _run_agent_with_tools(
        system_prompt=CRITIC_PROMPT,
        user_prompt=user_prompt,
        llm=llm,
        tools=tools,
        state=state,
        agent_name="Critic",
    )

    result["current_phase"] = "critic_complete"
    return result


def normalizer_node(state: ExtractionGraphState) -> Dict[str, Any]:
    """
    Normalizer agent: Adds normalized IDs to evidence items.
    """
    llm = get_normalizer_llm()
    tools = get_normalizer_tools()

    user_prompt = (
        "Normalize the evidence items by looking up database IDs. "
        "Call get_draft_extractions to get the items, "
        "then for each entity, use the lookup tools to find IDs. "
        "Finally, call save_evidence_items with the updated items "
        "and call finalize_extraction."
    )

    result = _run_agent_with_tools(
        system_prompt=NORMALIZER_PROMPT,
        user_prompt=user_prompt,
        llm=llm,
        tools=tools,
        state=state,
        agent_name="Normalizer",
    )

    result["current_phase"] = "normalizer_complete"
    return result


# =============================================================================
# HUMAN-IN-THE-LOOP (COMMENTED OUT)
# =============================================================================
#
# This feature allows human review of extractions before normalization.
# To enable:
#   1. Uncomment the human_review_node function
#   2. Uncomment the graph.add_node("human_review", human_review_node) in build_extraction_graph
#   3. Change the routing in route_after_critic to go to "human_review" instead of "normalizer"
#   4. Add interrupt_before=["human_review"] to graph.compile()
#
# The workflow will pause at human_review, write items to a JSON file,
# wait for human edits, then continue to normalizer.

"""
import time
from pathlib import Path

HUMAN_REVIEW_DIR = Path("outputs/human_review")
HUMAN_REVIEW_TIMEOUT = 300  # 5 minutes timeout for human review

def human_review_node(state: ExtractionGraphState) -> Dict[str, Any]:
    '''
    Human-in-the-Loop node: Pause for human review of extractions.

    This node:
    1. Writes draft extractions to a JSON file
    2. Waits for human to review/edit the file
    3. Reads back the edited file
    4. Continues to normalizer with updated extractions

    The human can:
    - Edit evidence items
    - Add new items
    - Remove incorrect items
    - Add notes/comments
    '''
    logger.info("=== HUMAN REVIEW NODE START ===")

    paper_id = state.get("paper_id", "unknown")
    draft_extractions = state.get("draft_extractions", [])

    # Create review directory
    HUMAN_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # Write extractions for human review
    review_file = HUMAN_REVIEW_DIR / f"{paper_id}_review.json"
    status_file = HUMAN_REVIEW_DIR / f"{paper_id}_status.txt"

    review_data = {
        "paper_id": paper_id,
        "instructions": [
            "Review and edit the evidence items below.",
            "You can modify, add, or remove items.",
            "When done, save this file and write 'APPROVED' to the status file.",
            "To reject and re-extract, write 'REJECT' to the status file.",
        ],
        "critique_summary": state.get("critique", {}).get("summary", "No critique available"),
        "item_count": len(draft_extractions),
        "evidence_items": draft_extractions,
    }

    review_file.write_text(json.dumps(review_data, indent=2))
    status_file.write_text("PENDING")

    logger.info(f"Human review file created: {review_file}")
    logger.info(f"Waiting for human review (timeout: {HUMAN_REVIEW_TIMEOUT}s)...")

    # Wait for human review
    start_time = time.time()
    while time.time() - start_time < HUMAN_REVIEW_TIMEOUT:
        status = status_file.read_text().strip().upper()

        if status == "APPROVED":
            # Read back the edited extractions
            edited_data = json.loads(review_file.read_text())
            updated_items = edited_data.get("evidence_items", draft_extractions)

            logger.info(f"Human review APPROVED: {len(updated_items)} items")

            # Update context
            ctx = get_context()
            ctx.draft_extractions = updated_items
            set_context(ctx)

            return {
                "draft_extractions": updated_items,
                "current_phase": "human_review_approved",
            }

        elif status == "REJECT":
            logger.info("Human review REJECTED: re-extraction requested")

            # Increment iteration to trigger re-extraction
            ctx = get_context()
            ctx.iteration_count += 1
            ctx.critique = {
                "overall_assessment": "NEEDS_REVISION",
                "summary": "Human reviewer requested re-extraction",
            }
            set_context(ctx)

            return {
                "iteration_count": ctx.iteration_count,
                "critique": ctx.critique,
                "current_phase": "human_review_rejected",
            }

        # Still pending - wait
        time.sleep(2)

    # Timeout - proceed with original extractions
    logger.warning(f"Human review timeout after {HUMAN_REVIEW_TIMEOUT}s, proceeding with original extractions")
    return {
        "current_phase": "human_review_timeout",
    }


def route_after_human_review(state: ExtractionGraphState) -> Literal["extractor", "normalizer"]:
    '''Route after human review: re-extract if rejected, normalize if approved.'''
    phase = state.get("current_phase", "")

    if phase == "human_review_rejected":
        iteration_count = state.get("iteration_count", 0)
        max_iterations = state.get("max_iterations", 3)
        if iteration_count < max_iterations:
            return "extractor"

    return "normalizer"


# ALTERNATIVE: LangGraph-native interrupt approach
# Instead of polling a file, use LangGraph's interrupt_before to pause execution.
# This is more idiomatic and integrates with LangGraph's state management.
#
# To use this approach:
# 1. Add interrupt_before=["human_review"] to graph.compile()
# 2. The graph will pause BEFORE the human_review node
# 3. Use graph.get_state(config) to get current extractions
# 4. Modify the state externally (via API or UI)
# 5. Use graph.update_state(config, {"draft_extractions": edited_items}) to update
# 6. Resume with graph.invoke(None, config) to continue from where it stopped
#
# Example usage:
#
#   # Initial run (pauses at human_review)
#   config = {"configurable": {"thread_id": "paper_123"}}
#   result = graph.invoke(initial_state, config)
#
#   # Check if paused
#   state = graph.get_state(config)
#   if state.next == ("human_review",):
#       # Get extractions for review
#       extractions = state.values["draft_extractions"]
#
#       # ... human edits the extractions ...
#
#       # Update state with edited extractions
#       graph.update_state(config, {"draft_extractions": edited_extractions})
#
#       # Resume execution
#       result = graph.invoke(None, config)
"""


# =============================================================================
# ROUTING LOGIC
# =============================================================================

def route_after_critic(state: ExtractionGraphState) -> Literal["extractor", "normalizer"]:
    """
    Route after Critic: either iterate back to Extractor or proceed to Normalizer.

    Returns:
        "extractor" if needs revision and under max iterations
        "normalizer" if approved or max iterations reached
    """
    critique = state.get("critique", {})
    assessment = critique.get("overall_assessment", "").upper()
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 3)

    logger.info(f"Routing after Critic: assessment={assessment}, iteration={iteration_count}/{max_iterations}")

    if assessment == "NEEDS_REVISION" and iteration_count < max_iterations:
        logger.info("Routing to Extractor for revision")
        return "extractor"
    else:
        if assessment == "NEEDS_REVISION":
            logger.info(f"Max iterations ({max_iterations}) reached, proceeding to Normalizer")
        else:
            logger.info(f"Assessment is {assessment}, proceeding to Normalizer")
        return "normalizer"


def should_continue(state: ExtractionGraphState) -> bool:
    """Check if extraction should continue."""
    return not state.get("is_complete", False)


# =============================================================================
# GRAPH CONSTRUCTION
# =============================================================================

def build_extraction_graph(checkpointer: Optional[BaseCheckpointSaver] = None) -> StateGraph:
    """
    Build the Extraction phase StateGraph.

    Graph structure:
        START -> planner -> extractor -> critic
                                          |
                    +--------------------+
                    |                    |
                    v                    v
                extractor          normalizer -> END
                (if NEEDS_REVISION)  (if APPROVED or max iterations)

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence/resume.
                     Required for thread_id-based state management per LangGraph v0.2+.

    Returns:
        Compiled StateGraph for Extraction phase
    """
    # Create graph with state schema
    graph = StateGraph(ExtractionGraphState)

    # Add nodes
    graph.add_node("planner", planner_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("critic", critic_node)
    graph.add_node("normalizer", normalizer_node)

    # Add edges
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "extractor")
    graph.add_edge("extractor", "critic")

    # Conditional edge after critic
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "extractor": "extractor",
            "normalizer": "normalizer",
        }
    )

    graph.add_edge("normalizer", END)

    # Compile with checkpointer for persistence (LangGraph v0.2+ pattern)
    # This enables: thread_id-based state management, resume capability, state history
    return graph.compile(checkpointer=checkpointer)


def run_extraction_phase(
    paper_content: Dict[str, Any],
    paper_content_text: str,
    paper_id: str = "unknown",
    max_iterations: int = 3,
) -> ExtractionGraphState:
    """
    Convenience function to run the Extraction phase.

    Args:
        paper_content: Structured paper content from Reader
        paper_content_text: Full text representation of paper
        paper_id: Identifier for the paper
        max_iterations: Maximum Critic→Extractor iterations

    Returns:
        State with final_extractions
    """
    # Build initial state
    initial_state: ExtractionGraphState = {
        "paper_id": paper_id,
        "thread_id": paper_id,
        "paper_content": paper_content,
        "paper_content_text": paper_content_text,
        "current_phase": "extraction_start",
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "is_complete": False,
        "errors": [],
        "messages": [],
        "extraction_plan": {},
        "draft_extractions": [],
        "final_extractions": [],
        "critique": {},
    }

    # Build and run graph
    graph = build_extraction_graph()
    result = graph.invoke(initial_state)

    return result


def run_full_pipeline(
    pdf_path: str,
    paper_id: str = "unknown",
    max_iterations: int = 3,
) -> ExtractionGraphState:
    """
    Run the full extraction pipeline (Reader + Extraction).

    Args:
        pdf_path: Path to PDF file
        paper_id: Identifier for the paper
        max_iterations: Maximum Critic→Extractor iterations

    Returns:
        Final state with all extractions
    """
    from .reader_graph import run_reader_phase

    # Phase 1: Reader
    logger.info("=== PHASE 1: READER ===")
    reader_result = run_reader_phase(pdf_path=pdf_path, paper_id=paper_id)

    if not reader_result.get("paper_content"):
        logger.error("Reader phase failed to extract content")
        return reader_result

    # Phase 2: Extraction
    logger.info("=== PHASE 2: EXTRACTION ===")
    extraction_result = run_extraction_phase(
        paper_content=reader_result["paper_content"],
        paper_content_text=reader_result["paper_content_text"],
        paper_id=paper_id,
        max_iterations=max_iterations,
    )

    return extraction_result
