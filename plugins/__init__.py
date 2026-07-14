"""
Plugin loader for Eling.
Scans this package directory for .py modules (skipping _private ones)
and collects their TOOLS dicts.

Also provides a ``@tool`` decorator for clean tool registration::

    from plugins import tool

    @tool("my_tool", "Does something useful")
    def my_tool(param1: str, param2: int = 0) -> str:
        \"\"\"Extended description.\"\"\"
        return f"{param1} = {param2}"

The decorator auto-generates a JSON schema from type hints and adds
the entry to a module-level ``TOOLS`` dict.
"""

import inspect
import importlib
import logging
import os
import pkgutil
from typing import get_type_hints

log = logging.getLogger("plugins")

# -- JSON schema type mapping -----------------------------------------

_PYTHON_TO_JSON = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
    type(None): {"type": "null"},
}


def _type_to_schema(tp) -> dict:
    """Convert a Python type hint to a JSON Schema property."""
    origin = getattr(tp, "__origin__", None)
    if origin is list:
        item_tp = getattr(tp, "__args__", (str,))[0]
        return {"type": "array", "items": _type_to_schema(item_tp)}
    if origin is dict:
        val_tp = getattr(tp, "__args__", (str,))[1]
        return {"type": "object", "additionalProperties": _type_to_schema(val_tp)}
    if origin is not None:
        return {"type": "string"}
    return _PYTHON_TO_JSON.get(tp, {"type": "string"})


def tool(name: str, description: str = "", auto_schema: bool = True):
    """Decorator that registers a function as an Eling plugin tool.

    Usage::

        @tool("my_tool", "Does something useful")
        def my_tool(param1: str, param2: int = 0) -> str:
            \"\"\"Docstring used as fallback description.\"\"\"
            ...

    Args:
        name: Tool name (used by the model).
        description: Short description for the model. Falls back to
                     the function's docstring if omitted.
        auto_schema: If True, generate JSON schema from type hints.
    """
    def decorator(func):
        nonlocal description
        if not description:
            description = (func.__doc__ or "").strip()

        schema = {"type": "object", "properties": {}, "required": []}
        if auto_schema:
            sig = inspect.signature(func)
            try:
                hints = get_type_hints(func)
            except Exception:
                hints = {}
            for pname, param in sig.parameters.items():
                if pname == "return":
                    continue
                tp = hints.get(pname, str)
                prop = _type_to_schema(tp)
                desc = f" ({tp.__name__})" if hasattr(tp, "__name__") else ""
                prop["description"] = desc
                schema["properties"][pname] = prop
                if param.default is inspect.Parameter.empty:
                    schema["required"].append(pname)

        # Register to the caller's module-level TOOLS dict
        frame = inspect.currentframe()
        if frame and frame.f_back:
            module_globals = frame.f_back.f_globals
            tools_dict = module_globals.setdefault("TOOLS", {})
            tools_dict[name] = {
                "function": func,
                "description": description,
                "parameters": schema,
            }
        return func
    return decorator


def load_plugins():
    """
    Scan this package's directory for .py modules (skip names starting
    with "_"). Each module is expected to define a module-level TOOLS
    dict of the form:

        TOOLS = {
            "tool_name": {
                "function": callable,
                "description": str,
                "parameters": {... JSON schema ...},
            }
        }

    Returns:
        (callables_dict, openai_tool_schemas_list)
        where callables_dict maps tool_name -> callable
        and openai_tool_schemas_list is a list of OpenAI tool schemas.
    """
    callables = {}
    schemas = []

    package_path = os.path.dirname(__file__)
    for importer, modname, ispkg in pkgutil.iter_modules([package_path]):
        if modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f".{modname}", __package__)
        except Exception as exc:
            log.warning("Failed to load plugin '%s': %s", modname, exc)
            continue

        tools_dict = getattr(mod, "TOOLS", {})
        if not isinstance(tools_dict, dict):
            log.warning("Plugin '%s' TOOLS is not a dict", modname)
            continue

        for tool_name, tool_def in tools_dict.items():
            func = tool_def.get("function")
            if not callable(func):
                log.warning(
                    "Plugin '%s' tool '%s': function not callable", modname, tool_name
                )
                continue
            callables[tool_name] = func
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    },
                }
            )
            log.debug("Loaded plugin tool: %s", tool_name)

    return callables, schemas
