#!/usr/bin/env python3
"""
Eling — a small autonomous agent framework with local memory,
auto-learning skill library, plugin loader, MCP client, and
OpenCode Zen as the model provider.
"""
import argparse
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import time
from memory import MemoryStore
from skills import SkillLibrary
from provider import ZenProvider
from workspace_manager import WorkspaceManager
from mcp_client import MCPManager
from plugins import load_plugins

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("eling")

BASE_SYSTEM_PROMPT = (
    "You are Eling, a helpful autonomous assistant running locally on "
    "the user's device. You have access to tools (local plugins and MCP "
    "servers, including a long-term memory server if configured). Use "
    "tools when they help; otherwise answer directly. Be concise."
)


def load_config(path: str = "config.json") -> dict:
    if not os.path.exists(path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, "config.json")
    with open(path) as f:
        return json.load(f)


def build_system_prompt(
    skills_hits: list,
    memory_hits: list,
) -> str:
    """Build the full system prompt by appending retrieved skills and memories."""
    parts = [BASE_SYSTEM_PROMPT]

    if skills_hits:
        parts.append("\n\n## Retrieved Skills")
        parts.append(
            "The following skills may be relevant to the current query. "
            "Use their bodies as guidance."
        )
        for skill, score in skills_hits:
            parts.append(
                f"\n### {skill.name} (uses={skill.uses}, "
                f"successes={skill.successes}, relevance={score:.3f})"
            )
            parts.append(skill.body)

    if memory_hits:
        parts.append("\n\n## Relevant Past Episodes")
        parts.append("Past exchanges that may be relevant to the current situation:")
        for entry, score in memory_hits:
            parts.append(
                f"\n--- (relevance={score:.3f}) ---\n"
                f"User: {entry.user_input}\n"
                f"Assistant: {entry.agent_output}\n"
                f"Outcome: {entry.outcome}"
            )

    return "\n".join(parts)


# ── Auto Ruff —────────────────────────────────────────────────────────

PY_FILE_RE = re.compile(r'(?:^|\s)(/[^\s]*\.py|[a-zA-Z0-9_./-]+\.py)')


def _auto_ruff_check(tool_results: list[dict], tui=None, *, workspace_manager=None) -> None:
    """Scan tool results for .py file references and run ruff check.

    Called after each tool round — catches syntax/quality issues
    immediately after code is created or edited.
    """
    files = set()
    for tr in tool_results:
        text = tr.get("content", "")
        for m in PY_FILE_RE.finditer(text):
            candidate = m.group(1).rstrip(".,;:!?)'\"")
            if os.path.isfile(candidate):
                files.add(candidate)

    if not files:
        return

    if tui:
        tui.console.print(
            f"  [dim {tui.DIM}]⏳ ruff check {' '.join(sorted(files))}[/]"
        )

    try:
        result = subprocess.run(
            ["ruff", "check", *sorted(files), "--output-format=concise"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            if tui:
                tui.console.print(f"  [bold green]✓ ruff[/]  [dim {tui.DIM}]clean[/]")
        else:
            # Show first few lines of output
            lines = result.stdout.strip().splitlines()
            snippet = "\n".join(lines[:5])
            if len(lines) > 5:
                snippet += f"\n  [dim {tui.DIM}]... and {len(lines)-5} more[/]"
            if tui:
                tui.console.print("  [bold red]✗ ruff[/]")
                tui.console.print(snippet)
            else:
                print(f"ruff: {len(lines)} issue(s)")
    except FileNotFoundError:
        pass  # ruff not installed
    except subprocess.TimeoutExpired:
        if tui:
            tui.console.print(f"  [dim {tui.DIM}]⚠ ruff timed out[/]")


def run_tool_calls(
    tool_calls: list,
    plugin_callables: dict,
    mcp_manager: MCPManager,
    tui=None,
) -> list[dict]:
    """Execute all tool calls from one model turn concurrently."""
    if not tool_calls:
        return []

    cpu_count = os.cpu_count() or 4
    max_workers = min(cpu_count, len(tool_calls))

    def _execute_one(tc: dict) -> dict:
        func_name = tc["function"]["name"]
        arguments_raw = tc["function"].get("arguments", "{}")
        if isinstance(arguments_raw, str):
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = arguments_raw

        # Remap file paths to workspace before executing
        if workspace_manager and workspace_manager.active:
            arguments = workspace_manager.remap_args(func_name, arguments)

        tool_call_id = tc.get("id", "")
        t0 = time.time()

        if func_name in plugin_callables:
            try:
                result = plugin_callables[func_name](**arguments)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
                ok = True
            except Exception as exc:
                result = f"(plugin error: {exc})"
                ok = False
        elif func_name.startswith("mcp__"):
            try:
                mcp_result = mcp_manager.call(func_name, arguments)
                result = json.dumps(mcp_result, ensure_ascii=False, default=str)
                ok = True
            except Exception as exc:
                result = f"(mcp error: {exc})"
                ok = False
        else:
            result = f"(unknown tool: {func_name})"
            ok = False

        # Remap workspace paths back to original in results
        if workspace_manager and workspace_manager.active:
            result = workspace_manager.remap_result(func_name, result)

        dur = time.time() - t0
        if tui:
            args_preview = ""
            if isinstance(arguments, dict):
                vals = [str(v)[:30] for v in arguments.values()]
                args_preview = ", ".join(vals)
            tui.tool_call(func_name, args_preview, dur, ok)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_execute_one, tool_calls))


def learn_from_exchange(
    provider: ZenProvider,
    user_input: str,
    agent_output: str,
    skills_lib: SkillLibrary,
    tui=None,
):
    """
    Make one extra call to the model asking whether to learn a skill
    from this exchange. If the model says learn=true, upsert into the
    skill library.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze conversations to extract reusable skills. "
                "Given a user query and an assistant response, decide if "
                "there is a generally useful skill or pattern that should "
                "be saved for future reference.\n\n"
                "Respond with STRICT JSON only (no markdown, no extra text):\n"
                '{"learn": true/false, "name": "short-name", '
                '"trigger": "phrase that triggers this skill", '
                '"body": "instructions for the skill"}'
            ),
        },
        {
            "role": "user",
            "content": f"User query: {user_input}\n\nAssistant response: {agent_output}",
        },
    ]
    try:
        resp = provider.chat(messages, max_tokens=500, temperature=0.2)
        content = resp.get("content", "")
        if content.startswith("```"):
            lines = content.strip().splitlines()
            content = "\n".join(line for line in lines if not line.startswith("```"))
        data = json.loads(content)
        if data.get("learn") and data.get("name"):
            skills_lib.upsert(
                name=data["name"],
                trigger=data.get("trigger", user_input),
                body=data.get("body", agent_output),
            )
            log.info("Learned new skill: %s", data["name"])
            if tui:
                tui.learned_skill(data["name"])
    except Exception as exc:
        log.debug("Learn-from-exchange skipped: %s", exc)


def run_turn(
    provider: ZenProvider,
    user_input: str,
    memory_store: MemoryStore,
    skills_lib: SkillLibrary,
    plugin_callables: dict,
    plugin_schemas: list,
    mcp_manager: MCPManager,
    config: dict,
    tui=None,
    *,
    conversation_history: list | None = None,
) -> tuple[str, list]:
    """Process one turn: retrieve context, loop tool rounds, log, learn.

    Returns (response_text, conversation_history) so history can be
    passed to the next turn for continuity.
    """
    history = list(conversation_history) if conversation_history else []
    max_tool_rounds = min(config.get("max_tool_rounds", 15), 100)

    # Retrieve relevant context
    skills_hits = skills_lib.relevant(user_input, k=3)
    memory_hits = memory_store.relevant(user_input, k=5)

    # Display retrieved context
    if tui and (skills_hits or memory_hits):
        tui.recall_header()
        for skill, score in skills_hits:
            tui.context_hit(f"skill:{skill.name}", skill.body, score)
        for entry, score in memory_hits:
            tui.context_hit("memory", entry.user_input, score)
        tui.console.print()

    system_prompt = build_system_prompt(skills_hits, memory_hits)

    # Build messages: system + history (last 10 exchanges) + new user input
    messages = [{"role": "system", "content": system_prompt}]
    # Keep last 20 history entries (10 user/assistant pairs) to stay within token limits
    messages.extend(history[-20:])
    messages.append({"role": "user", "content": user_input})

    all_tool_schemas = list(plugin_schemas)
    all_tool_schemas.extend(mcp_manager.openai_tools())

    final_content = ""

    # Initialize workspace manager for copy-on-write editing
    workspace_manager = WorkspaceManager()
    workspace_setup_done = False

    for round_num in range(max_tool_rounds):
        resp = provider.chat(
            messages,
            tools=all_tool_schemas if all_tool_schemas else None,
            max_tokens=16384,
            temperature=0.4,
        )

        content = resp.get("content") or ""
        tool_calls = resp.get("tool_calls")

        # Show model's chain-of-thought reasoning if present
        reasoning = resp.get("reasoning_content") or ""
        if reasoning and tui:
            tui.reasoning(reasoning)

        # If content is empty but we have reasoning (e.g. max_tokens still too low),
        # use the reasoning as fallback so the agent can still respond
        if not content and reasoning:
            content = f"*[reasoning overshadows response — increase max_tokens for cleaner output]*\n\n{reasoning}"

        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            final_content = content
            break

        # Set up workspace on first tool round with file paths
        if not workspace_setup_done:
            workspace_setup_done = workspace_manager.setup_from_tool_calls(tool_calls)
            if workspace_setup_done and tui:
                tui.console.print(
                    f"  [dim {tui.DIM}]📦 workspace: {workspace_manager.summary()}[/]"
                )

        tool_results = run_tool_calls(
            tool_calls, plugin_callables, mcp_manager, tui,
            workspace_manager=workspace_manager,
        )
        messages.extend(tool_results)
        _auto_ruff_check(tool_results, tui, workspace_manager=workspace_manager)

    if not final_content and messages:
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                final_content = msg["content"]
                break

    # If we still have no content or the last round ended on tool_calls,
    # make one final provider call asking for a summary
    if not final_content or any(
        m.get("tool_calls") for m in messages[-3:]
    ):
        if tui:
            tui.reasoning("⏰ Tool rounds exhausted — requesting summary from model...")
        messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum number of tool-call rounds. "
                "Please provide a summary of what you've discovered so far. "
                "Be concise."
            )
        })
        final_resp = provider.chat(messages, temperature=0.3)
        summary = final_resp.get("content") or ""
        if summary:
            final_content = summary

    # Sync workspace changes back to original paths
    synced = workspace_manager.sync_back()
    if synced and tui:
        tui.console.print(
            f"  [dim {tui.DIM}]✓ synced {synced} file(s) back to original paths[/]"
        )

    memory_store.add(
        user_input=user_input,
        agent_output=final_content,
        outcome="completed" if final_content else "failed",
    )

    for skill, _score in skills_hits:
        skills_lib.record_use(skill.name, success=bool(final_content))

    learn_from_exchange(provider, user_input, final_content, skills_lib, tui)

    # Update conversation history with this turn
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": final_content})
    # Keep only last 20 exchanges (40 messages) max
    if len(history) > 40:
        history = history[-40:]

    return final_content, history


def _count_mcp_daemons() -> int:
    """Count running MCP daemon processes (brain, continuum, termux, etc.)."""
    try:
        r = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
        count = 0
        for line in r.stdout.split("\n"):
            if "mcp" in line.lower() and "grep" not in line:
                if any(name in line for name in ("brain-mcp", "continuum-mcp", "termux-mcp")):
                    count += 1
        return count
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description="Eling — autonomous agent")
    parser.add_argument(
        "query", nargs="*",
        help="Optional query (one-shot mode). If omitted, runs interactive REPL.",
    )
    parser.add_argument(
        "--compact", action="store_true",
        help="Compact display mode (no banner, minimal output)",
    )
    args = parser.parse_args()

    config = load_config()
    zen_api_key = config.get("zen_api_key", os.environ.get("ZEN_API_KEY", ""))
    if not zen_api_key or zen_api_key == "REPLACE_WITH_YOUR_ZEN_KEY":
        print(
            "ERROR: Set zen_api_key in config.json or ZEN_API_KEY env var.\n"
            "Get a key at https://opencode.ai/zen"
        )
        sys.exit(1)

    provider = ZenProvider(
        api_key=zen_api_key,
        model=config.get("zen_model", "zen/default"),
        base_url=config.get("zen_base_url", "https://opencode.ai/zen/v1"),
    )
    memory_store = MemoryStore(config.get("memory_db", "agent_memory.db"))
    skills_lib = SkillLibrary(config.get("skills_db", "agent_skills.db"))
    plugin_callables, plugin_schemas = load_plugins()

    mcp_servers = {
        k: v for k, v in config.get("mcp_servers", {}).items() if not k.startswith("_")
    }
    mcp_manager = MCPManager(mcp_servers)

    # ── Initialise TUI ──────────────────────────────────────────────
    if not args.compact:
        from tui import ElingTUI
        tui = ElingTUI()
        tui.console.clear()
    else:
        tui = None

    # Count skills/memories for banner
    skill_count = len(skills_lib.relevant("", k=9999))
    mem_count = len(memory_store.all())

    if tui:
        tui.banner(
            skills=skill_count,
            memories=mem_count,
            plugins=len(plugin_schemas),
            mcp=len(mcp_manager.connections) + _count_mcp_daemons(),
            model=config.get("zen_model", ""),
        )
        tui.console.print(
            f"[dim {tui.DIM}]Type your query or 'exit' to quit.[/]"
        )
        tui.console.print()
    else:
        log.info(
            "Eling ready — %d plugins, %d MCP server(s), %d skills, %d memories",
            len(plugin_schemas), len(mcp_manager.connections) + _count_mcp_daemons(),
            skill_count, mem_count,
        )

    try:
        conversation_history: list = []
        if args.query:
            query_text = " ".join(args.query)
            if tui:
                tui.turn_start(query_text)
            else:
                print(f"\n> {query_text}")

            response, conversation_history = run_turn(
                provider, query_text,
                memory_store, skills_lib,
                plugin_callables, plugin_schemas,
                mcp_manager, config, tui,
                conversation_history=conversation_history,
            )

            if tui:
                tui.assistant(response)
                tui.turn_end()
            else:
                print(response)
        else:
            while True:
                try:
                    user_input = input("\n> " if not tui else "").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    break

                if tui:
                    tui.turn_start(user_input)
                else:
                    print(f"\n> {user_input}")

                if tui:
                    with tui.thinking():
                        response, conversation_history = run_turn(
                            provider, user_input,
                            memory_store, skills_lib,
                            plugin_callables, plugin_schemas,
                            mcp_manager, config, tui,
                            conversation_history=conversation_history,
                        )
                else:
                    response, conversation_history = run_turn(
                        provider, user_input,
                        memory_store, skills_lib,
                        plugin_callables, plugin_schemas,
                        mcp_manager, config, tui,
                        conversation_history=conversation_history,
                    )

                if tui:
                    tui.assistant(response)
                    tui.turn_end()
                else:
                    print(response)
    finally:
        log.info("Shutting down...")
        mcp_manager.stop_all()
        memory_store.close()
        skills_lib.close()


if __name__ == "__main__":
    main()
