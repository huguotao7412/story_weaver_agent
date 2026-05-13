# app/agents/registry.py
"""Agent registry — maps agent names in workflow.yaml to node callable functions."""

agent_registry = {}


def register(name: str):
    """Decorator to register an agent node function by name."""
    def decorator(fn):
        agent_registry[name] = fn
        return fn
    return decorator


def get_agent_node(name: str):
    """Look up a registered agent node by name."""
    if name not in agent_registry:
        raise KeyError(f"Agent '{name}' not found in registry. Registered: {list(agent_registry.keys())}")
    return agent_registry[name]
