"""
Plugin loader for Eling.
Scans this package directory for .py modules (skipping _private ones)
and collects their TOOLS dicts.
"""

import importlib
import logging
import os
import pkgutil

log = logging.getLogger("plugins")


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
