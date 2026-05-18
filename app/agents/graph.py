# app/agents/graph.py
"""Generic workflow orchestrator — reads workflow.yaml to build a LangGraph StateGraph."""
from pathlib import Path

import yaml
from langgraph.graph import StateGraph, START, END

from app.core.state import TomatoNovelState
from app.agents.registry import get_agent_node
from app.agents.routers import planner_router, editor_router, human_review_router

# Agent module imports — triggers @register decorators to populate the registry.
# These are used by get_agent_node() when building the workflow from YAML config.
import app.agents.book_planner          # noqa: F401  registers "book_planner"
import app.agents.volume_planner        # noqa: F401  registers "volume_planner"
import app.agents.phase_planner         # noqa: F401  registers "phase_planner"
import app.agents.chapter_planner       # noqa: F401  registers "chapter_planner"
import app.agents.supervisor            # noqa: F401  registers "human_review"
import app.agents.workers.continuity_editor  # noqa: F401  registers "continuity_editor"
import app.agents.workers.chapter_writer     # noqa: F401  registers "chapter_writer"
import app.agents.workers.memory_keeper      # noqa: F401  registers "memory_keeper"
import app.agents.workers.style_analyzer     # noqa: F401  registers "style_analyzer"

WORKFLOW_PATH = Path(__file__).resolve().parent.parent.parent / "workflow.yaml"

# Python router function lookup for conditional edges
_ROUTER_FUNCTIONS = {
    "planner_router": planner_router,
    "editor_router": editor_router,
    "human_review_router": human_review_router,
}

# Mapping from node names in workflow.yaml to the source nodes that feed their
# conditional edge.  Determined by the conditional_routes keys in the YAML.
_ROUTE_SOURCE_NODES = {
    "planner_router": START,
    "editor_router": "Continuity_Editor",
    "human_review_router": "Human_Review",
}


def build_workflow() -> StateGraph:
    """Read workflow.yaml and compile a StateGraph with registered agent nodes."""
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    workflow = StateGraph(TomatoNovelState)

    # Register all nodes
    for node_def in config["nodes"]:
        node_name = node_def["name"]
        agent_key = node_def["agent"]
        node_fn = get_agent_node(agent_key)
        workflow.add_node(node_name, node_fn)

    # Add fixed edges
    for edge in config["edges"]:
        from_node = edge["from"]
        to_node = edge["to"]
        target = END if to_node == "END" else to_node
        workflow.add_edge(from_node, target)

    # Build conditional edges from YAML config.
    # The YAML only declares topology (targets); actual routing logic lives in routers.py.
    conditional_routes = config.get("conditional_routes", {})
    for route_name, route_def in conditional_routes.items():
        router_fn = _ROUTER_FUNCTIONS[route_name]
        source_node = _ROUTE_SOURCE_NODES[route_name]
        targets = {t: t for t in route_def["targets"]}
        workflow.add_conditional_edges(source_node, router_fn, targets)

    return workflow
