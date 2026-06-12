"""
tools/registry.py — Tool registry with async error isolation and per-agent authorization.

Every tool in this project is registered here via @safe_tool(agents=[...]).
No tool can be used by an agent that is not listed in its agents parameter.
load_all_tools() is called once at process startup; it imports every module in
the tools/ package which fires the @safe_tool decorators and populates _REGISTRY.
"""

import asyncio
import functools
import importlib
import inspect
import pkgutil
from typing import Optional

from langchain.tools import tool as langchain_tool
from langchain_core.tools import BaseTool

# Per-agent tool registry: maps agent_name → list of LangChain BaseTools
_REGISTRY: dict[str, list[BaseTool]] = {}


def safe_tool(agents: list[str], timeout_seconds: Optional[float] = None):
    """
    Decorator that wraps a tool function with async error isolation and registers
    it in the tool registry for the specified agent(s).

    On any exception or timeout the wrapper returns {"error": "..."} instead of
    raising — the ReAct agent receives this as a tool observation and can reason
    about the failure without crashing the agent process.

    Args:
        agents: list of agent names authorized to use this tool
                e.g. ["sales"], ["inventory"], ["action_executor"]
        timeout_seconds: optional per-call timeout in seconds.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    if timeout_seconds is not None:
                        return await asyncio.wait_for(result, timeout=timeout_seconds)
                    return await result
                return result
            except asyncio.TimeoutError:
                return {
                    "error": f"Tool '{fn.__name__}' timed out after {timeout_seconds}s"
                }
            except Exception as e:
                return {
                    "error": f"Tool '{fn.__name__}' failed: {type(e).__name__}: {e}"
                }

        # Explicitly copy the original signature so LangChain builds the correct input schema
        wrapper.__signature__ = inspect.signature(fn)

        lc_tool = langchain_tool(wrapper)
        for agent in agents:
            _REGISTRY.setdefault(agent, []).append(lc_tool)
        return lc_tool

    return decorator


def get_tools_for_agent(agent_name: str) -> list[BaseTool]:
    """Return the list of tools authorized for the named agent.

    Returns an empty list if the agent is unknown or load_all_tools() has not
    been called yet.
    """
    return list(_REGISTRY.get(agent_name, []))


def load_all_tools() -> None:
    """Import every tool module in the tools/ package.

    The act of importing fires the @safe_tool decorators, populating _REGISTRY.
    Safe to call multiple times — Python's module cache prevents re-imports.
    Skips registry.py itself.
    """
    import tools as _tools_pkg

    for _, module_name, _ in pkgutil.iter_modules(_tools_pkg.__path__):
        if module_name == "registry":
            continue
        importlib.import_module(f"tools.{module_name}")
