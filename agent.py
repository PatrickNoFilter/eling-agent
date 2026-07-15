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
import requests
import shutil
import subprocess
import sys
import time
from memory import MemoryStore
from skills import SkillLibrary
from provider import ZenProvider
from mcp_client import MCPManager
from plugins import load_plugins

from rich.logging import RichHandler
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False, show_time=False)],
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
    if not os.path.exists(path):
        home_cfg = os.path.join(os.path.expanduser("~"), "eling-agent", "config.json")
        if os.path.exists(home_cfg):
            path = home_cfg
    if not os.path.exists(path):
        # Bootstrap from example if available
        example = path.replace("config.json", "config.example.json")
        if os.path.exists(example):
            shutil.copy2(example, path)
            print(f"Created {path} from {example} — edit to add your API key.")
        else:
            print(
                "ERROR: No config.json found. Copy config.example.json to "
                "config.json and set your zen_api_key (or set ZEN_API_KEY env var)."
            )
            sys.exit(1)
    with open(path) as f:
        cfg = json.load(f)
        cfg["_config_path"] = path
        return cfg


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


# ── Auto Ruff + Auto Pytest —──────────────────────────────────────────

PY_FILE_RE = re.compile(r'(?:^|\s)(/[^\s]*\.py|[a-zA-Z0-9_./-]+\.py)')


def _extract_py_files(tool_results: list[dict]) -> set[str]:
    """Extract .py file paths from tool result content."""
    files: set[str] = set()
    for tr in tool_results:
        text = tr.get("content", "")
        for m in PY_FILE_RE.finditer(text):
            candidate = m.group(1).rstrip(".,;:!?)'\"")
            if os.path.isfile(candidate):
                files.add(candidate)
    return files


def _auto_ruff_check(tool_results: list[dict], tui=None) -> None:
    """Scan tool results for .py file references and run ruff check.

    Called after each tool round — catches syntax/quality issues
    immediately after code is created or edited.
    """
    files = _extract_py_files(tool_results)
    if not files:
        return

    if tui:
        tui.console.print(
            f"  [dim {tui.MUTEDBLUE}]⏳ ruff check {' '.join(sorted(files))}[/]"
        )

    try:
        result = subprocess.run(
            ["ruff", "check", *sorted(files), "--output-format=concise"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            if tui:
                tui.console.print(f"  [bold {tui.GREEN}]✓ ruff[/]  [dim {tui.MUTEDBLUE}]clean[/]")
        else:
            # Auto-fix with safe fixes
            if tui:
                tui.console.print(f"  [dim {tui.MUTEDBLUE}]  ↻ ruff --fix ...[/]")
            subprocess.run(
                ["ruff", "check", *sorted(files), "--fix", "--quiet"],
                capture_output=True, timeout=15,
            )
            # Re-check
            recheck = subprocess.run(
                ["ruff", "check", *sorted(files), "--output-format=concise"],
                capture_output=True, text=True, timeout=15,
            )
            if recheck.returncode == 0:
                if tui:
                    tui.console.print(f"  [bold {tui.GREEN}]✓ ruff[/]  [dim {tui.MUTEDBLUE}]fixed and clean[/]")
            else:
                lines = recheck.stdout.strip().splitlines()
                snippet = "\n".join(lines[:5])
                if len(lines) > 5:
                    snippet += f"\n  [dim {tui.MUTEDBLUE}]... and {len(lines)-5} more[/]"
                if tui:
                    tui.console.print(f"  [bold {tui.RED}]⚠ ruff (unfixable)[/]")
                    tui.console.print(snippet)
                else:
                    print(f"ruff: {len(lines)} issue(s) remaining")
    except FileNotFoundError:
        pass  # ruff not installed
    except subprocess.TimeoutExpired:
        if tui:
            tui.console.print(f"  [dim {tui.MUTEDBLUE}]⚠ ruff timed out[/]")


def _auto_pytest(tool_results: list[dict], tui=None) -> str | None:
    """Scan tool results for test files and auto-run pytest on them.

    Runs after each tool round when the model creates or edits test files.
    - If explicit test_*.py files are found, run pytest on those.
    - If source files are modified, look for matching tests/test_<name>.py.
    - Silently skips when no test files match (no noise).

    Returns a markdown summary of failures (for the model to fix in the
    next round) or None if all passed / nothing to run.
    """
    all_files = _extract_py_files(tool_results)
    if not all_files:
        return

    test_targets: set[str] = set()

    for f in all_files:
        rel = os.path.relpath(f)
        # Direct test file match
        if "/test_" in rel or rel.startswith("test_") or "/tests/" in rel:
            test_targets.add(f)
        else:
            # Source file → look for matching test
            basename = os.path.splitext(os.path.basename(f))[0]
            candidate = os.path.join(os.path.dirname(f), "tests", f"test_{basename}.py")
            if os.path.isfile(candidate):
                test_targets.add(candidate)
            # Also check project-root tests/
            root_test = os.path.join(
                os.path.dirname(os.path.dirname(f)), "tests", f"test_{basename}.py"
            )
            if root_test != candidate and os.path.isfile(root_test):
                test_targets.add(root_test)

    if not test_targets:
        return None

    if tui:
        labels = [os.path.relpath(t) for t in sorted(test_targets)]
        tui.console.print(
            f"  [dim {tui.MUTEDBLUE}]⏳ pytest {' '.join(labels)}[/]"
        )

    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", *sorted(test_targets), "-x", "--tb=short"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            if tui:
                last_line = (result.stdout.strip().splitlines() or ["all passed"])[-1]
                tui.console.print(f"  [bold {tui.GREEN}]✓ pytest[/]  [dim {tui.MUTEDBLUE}]{last_line}[/]")
            return None
        else:
            # Build a compact failure summary for the model
            lines = result.stdout.strip().splitlines()
            failure_lines = [line for line in lines if "FAILED" in line or "ERROR" in line or "assert" in line]
            summary = "\n".join(failure_lines[-15:]) if failure_lines else result.stdout.strip()[:800]
            if tui:
                tui.console.print(f"  [bold {tui.RED}]✗ pytest[/]")
                for line in (failure_lines or lines)[:5]:
                    tui.console.print(f"  {line}")
            return f"*Auto-pytest found failures:*\n```\n{summary}\n```\n*Fix the test(s) above and re-run.*"
    except FileNotFoundError:
        return None  # pytest not installed
    except subprocess.TimeoutExpired:
        if tui:
            tui.console.print(f"  [dim {tui.MUTEDBLUE}]⚠ pytest timed out (120s)[/]")
        return "*Auto-pytest timed out (120s).*"


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

        tool_call_id = tc.get("id", "")

        if tui:
            args_preview = ""
            if isinstance(arguments, dict):
                items = []
                for k, v in arguments.items():
                    items.append(f"{k}={str(v)}")
                args_preview = ", ".join(items)
            tui.tool_start(func_name, args_preview)

        start_time = time.monotonic()
        ok = True
        if func_name in plugin_callables:
            try:
                result = plugin_callables[func_name](**arguments)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                result = f"(plugin error: {exc})"
                ok = False
        elif func_name.startswith("mcp__"):
            try:
                mcp_result = mcp_manager.call(func_name, arguments)
                result = json.dumps(mcp_result, ensure_ascii=False, default=str)
            except Exception as exc:
                result = f"(mcp error: {exc})"
                ok = False
        else:
            result = f"(unknown tool: {func_name})"
            ok = False

        duration = time.monotonic() - start_time

        if tui:
            tui.tool_end(func_name, result, duration, ok)

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
    _max = 2000
    truncated_input = user_input[:_max] + ("..." if len(user_input) > _max else "")
    truncated_output = agent_output[:_max] + ("..." if len(agent_output) > _max else "")

    messages = [
        {
            "role": "system",
            "content": (
                "You extract reusable skill patterns from conversations.\n\n"
                "A skill is worth learning when the assistant solved a real problem — "
                "wrote code, debugged, explained a technique, or performed multi-step work.\n\n"
                "Examples:\n"
                '- {"learn": true, "name": "live-elapsed-timer", "trigger": "add time counter", "body": "1) Record start time 2) Spawn daemon thread updating display every 0.5s 3) Show elapsed seconds 4) Join on exit"}\n'
                '- {"learn": true, "name": "system-health-check", "trigger": "check system health", "body": "Run top -bn1, free -h, df -h, uptime to get system metrics"}\n\n'
                "Respond STRICT JSON only. No markdown, no extra text.\n"
                'If learn is false: {"learn": false}'
            ),
        },
        {
            "role": "user",
            "content": f"User query: {truncated_input}\n\nAssistant response: {truncated_output}",
        },
    ]
    try:
        resp = provider.chat(messages, max_tokens=500, temperature=0.3)
        content = resp.get("content", "")
        if not content:
            return
        lines = content.strip().splitlines()
        filtered = [line for line in lines if not line.startswith("```")]
        content = "\n".join(filtered).strip()
        data = json.loads(content)
        if data.get("learn") and data.get("name"):
            name = data["name"].strip()
            body = (data.get("body") or agent_output[:1000]).strip()
            trigger = (data.get("trigger") or user_input[:200]).strip()
            # Quality heuristic: require meaningful body content
            if len(body) < 50:
                log.debug("Skill '%s' body too short (%d chars), skipping", name, len(body))
                return
            # Quality heuristic: reject overly generic names
            generic_names = {"fix", "debug", "help", "solve", "patch", "workaround"}
            if name.lower() in generic_names:
                log.debug("Skill name '%s' too generic, skipping", name)
                return
            skills_lib.upsert(
                name=name,
                trigger=trigger,
                body=body,
            )
            log.info("Learned new skill: %s", name)
            if tui:
                tui.learned_skill(name)
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
    max_tool_rounds = config.get("max_tool_rounds", 200)
    max_turn_duration = config.get("max_turn_duration", 300)  # wall-clock timeout (seconds)
    _turn_start = time.monotonic()

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

    for round_num in range(max_tool_rounds):
        # Wall-clock timeout check
        elapsed = time.monotonic() - _turn_start
        if elapsed > max_turn_duration:
            if tui:
                tui.console.print(f"  [{tui.MIDBLUE}]⏰ Turn timed out ({elapsed:.0f}s > {max_turn_duration}s)[/]")
            break

        try:
            resp = provider.chat(
                messages,
                tools=all_tool_schemas if all_tool_schemas else None,
                max_tokens=16384,
                temperature=0.4,
            )
        except requests.exceptions.RequestException as exc:
            error_msg = f"*Model request failed after retries: {exc}*"
            if tui:
                tui.console.print(f"  [bold {tui.RED}]✗ {error_msg}[/]")
            # Final attempt: hand the error back as the response
            final_content = error_msg
            break

        content = resp.get("content") or ""
        tool_calls = resp.get("tool_calls")

        # Show model's chain-of-thought reasoning if present
        reasoning = resp.get("reasoning_content") or ""
        if reasoning and tui and config.get("show_reasoning", True):
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

        tool_results = run_tool_calls(
            tool_calls, plugin_callables, mcp_manager, tui,
        )
        _auto_ruff_check(tool_results, tui)
        pytest_fail = _auto_pytest(tool_results, tui)
        if pytest_fail:
            tool_results.append({
                "role": "tool",
                "content": pytest_fail,
                "tool_call_id": "_auto_pytest",
            })
        messages.extend(tool_results)

    if not final_content and messages:
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                final_content = msg["content"]
                break

    # If we still have no content or the last round ended on tool_calls,
    # make one final provider call asking for a summary
    if not final_content or (
        next((m for m in reversed(messages) if m["role"] == "assistant"), {}).get("tool_calls")
    ):
        if tui:
            tui.reasoning("⏰ Tool rounds exhausted — requesting summary from model...")
        messages.append({
            "role": "user",
            "content": (
                "Tool rounds exhausted. "
                "Please provide a summary of what you've discovered so far. "
                "Be concise."
            )
        })
        final_resp = provider.chat(messages, temperature=0.3)
        summary = final_resp.get("content") or ""
        if summary:
            final_content = summary

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
    _start_time = time.time()
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
    # Resolve relative DB paths based on config file location
    _cfg_dir = os.path.dirname(os.path.abspath(config.get("_config_path", "config.json")))
    for _key in ("memory_db", "skills_db"):
        _val = config.get(_key)
        if _val and not os.path.isabs(_val):
            config[_key] = os.path.join(_cfg_dir, _val)
    zen_api_key = os.environ.get("ZEN_API_KEY") or config.get("zen_api_key", "")
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
    # Clean up stale WAL/SHM files from previous uncheckpointed closes
    _mem_path = config.get("memory_db", "agent_memory.db")
    for _ext in ("-wal", "-shm"):
        _orphan = _mem_path + _ext
        if os.path.exists(_orphan):
            try:
                os.remove(_orphan)
            except OSError:
                pass
    memory_store = MemoryStore(_mem_path)
    skills_lib = SkillLibrary(config.get("skills_db", "agent_skills.db"))
    # Prune stale skills on startup
    try:
        pruned = skills_lib.prune_unused(days=30)
        if pruned:
            log.info("Pruned %d unused skill(s) older than 30 days", pruned)
    except Exception as exc:
        log.debug("Skill prune (unused) skipped: %s", exc)
    try:
        low_pruned = skills_lib.prune_low_performer()
        if low_pruned:
            log.info("Pruned %d low-performing skill(s)", low_pruned)
    except Exception as exc:
        log.debug("Skill prune (low-performer) skipped: %s", exc)

    # ── Memory pruning on startup ──────────────────────────────────
    try:
        dup_pruned = memory_store.prune_duplicates()
        if dup_pruned:
            log.info("Pruned %d duplicate memory entries", dup_pruned)
    except Exception as exc:
        log.debug("Duplicate pruning skipped: %s", exc)
    try:
        old_pruned = memory_store.prune_old(keep=1000)
        if old_pruned:
            log.info("Pruned %d old memory entries (keeping %d)", old_pruned, 1000)
    except Exception as exc:
        log.debug("Old-memory pruning skipped: %s", exc)
    plugin_callables, plugin_schemas = load_plugins()

    mcp_servers = {
        k: v for k, v in config.get("mcp_servers", {}).items() if not k.startswith("_")
    }
    mcp_manager = MCPManager(mcp_servers)

    # ── Initialise TUI ──────────────────────────────────────────────
    if not args.compact:
        from tui import ElingTUI
        tui = ElingTUI(session_start=_start_time, theme=config.get("theme"))
        # Apply verbose_tool_output config
        if not config.get("verbose_tool_output", True):
            tui.set_verbose_tool_output(False)
        tui.clear_screen()
    else:
        print("\033[3J\033[2J\033[H", end="")
        tui = None

    # Count skills/memories for banner
    skill_count = len(skills_lib.relevant("", k=9999))
    mem_count = memory_store.count()

    if tui:
        tui.banner(
            skills=skill_count,
            memories=mem_count,
            plugins=len(plugin_schemas),
            mcp=len(mcp_manager.connections) + _count_mcp_daemons(),
            model=config.get("zen_model", ""),
            theme=tui._theme_name,
        )
        tui.console.print(
            f"[dim {tui.MUTEDBLUE}]Type your query or 'exit' to quit.[/]"
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
                    if tui:
                        user_input = tui.input_prompt().strip()
                    else:
                        user_input = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    if tui:
                        tui.clear_screen()
                        tui.console.print("[dim]Goodbye![/]")
                    else:
                        print("\033[3J\033[2J\033[H", end="")
                        print("Goodbye!")
                    break

                if not user_input:
                    continue
                if user_input.strip() == "/new":
                    if tui:
                        tui.clear_screen()
                    else:
                        print("\033[3J\033[2J\033[H", end="")
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    new_dir = os.path.join(os.path.expanduser("~"), "eling-workspace", f"session-{ts}")
                    os.makedirs(new_dir, exist_ok=True)
                    for fname in ("config.json", config.get("memory_db", "agent_memory.db"), config.get("skills_db", "agent_skills.db")):
                        src = os.path.abspath(fname)
                        dst = os.path.join(new_dir, os.path.basename(fname))
                        if os.path.exists(src) and not os.path.exists(dst):
                            shutil.copy2(src, dst)
                    if tui:
                        tui.console.print(f"[bold {tui.MIDBLUE}]\u267b Restarting in {new_dir}...[/]")
                    mcp_manager.stop_all()
                    memory_store.close()
                    skills_lib.close()
                    os.chdir(new_dir)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                if user_input.lower() in ("exit", "quit", "/exit"):
                    if tui:
                        tui.clear_screen()
                        tui.console.print("[dim]Goodbye![/]")
                    else:
                        print("\033[3J\033[2J\033[H", end="")
                    break

                if tui:
                    tui.turn_start(user_input, show_input=False)
                else:
                    print(f"\n> {user_input}")

                try:
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
                except KeyboardInterrupt:
                    print()
                    if tui:
                        tui.console.print(f"  [{tui.MIDBLUE}]⏹ Interrupted[/]")
                    else:
                        print("Interrupted.")
                    response = ""
                    continue

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
