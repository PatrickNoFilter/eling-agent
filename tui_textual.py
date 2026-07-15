#!/usr/bin/env python3
"""
Eling Textual TUI — split-pane conversation UI with permanent input bar,
elapsed timer, and real Eling agent integration via run_turn().

Usage:
    python tui_textual.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Rich ──────────────────────────────────────────────────────────
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.style import Style as RichStyle

# ── Textual ───────────────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, Input, RichLog, Static, Button
from textual.binding import Binding
from textual import work

# ── Path setup ────────────────────────────────────────────────────
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

# ── Theme palette ────────────────────────────────────────────────
ACCENT    = "#60a5fa"
MIDBLUE   = "#3b82f6"
LIGHTBLUE = "#93c5fd"
MUTEDBLUE = "#bfdbfe"
DEEPBLUE  = "#1e3a5f"
TEXT      = "#f0f9ff"
BG        = "#0f172a"
GREEN     = "#4ade80"
RED       = "#f87171"
YELLOW    = "#fbbf24"


def _fmt_time(seconds: float) -> str:
    hours, rem = divmod(int(seconds), 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    elif mins:
        return f"{mins}m {secs}s"
    else:
        return f"{secs}s"


def _fmt_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════
#  Textual TUI — drop-in replacement for original ElingTUI
# ═══════════════════════════════════════════════════════════════════

class ElingTextualTUI(App):
    """Split-pane conversation TUI with permanent input bar, elapsed timer,
    and real Eling agent integration.

    Implements the same interface (``assistant()``, ``user_input()``,
    ``reasoning()``, ``tool_call()``, …) as the original ``ElingTUI``
    from ``tui.py``, so it can be passed to ``run_turn()``.
    """

    # ── CSS ────────────────────────────────────────────────────────
    CSS = f"""
    Screen {{
        background: {BG};
    }}

    #app-container {{
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto auto;
        height: 100%;
    }}

    #conversation {{
        background: {BG};
        border: none;
        margin: 0 1;
        overflow-y: auto;
        scrollbar-color: {MIDBLUE} {DEEPBLUE};
        scrollbar-size-vertical: 1;
    }}

    #input-bar {{
        background: {DEEPBLUE};
        height: auto;
        padding: 0 1;
        border-top: solid {MIDBLUE};
        min-height: 3;
    }}

    #status-bar {{
        background: {DEEPBLUE};
        height: 1;
        padding: 0 2;
    }}

    #input-field {{
        background: #1e3a5f;
        color: {TEXT};
        border: none;
        width: 1fr;
        height: 3;
        padding: 0 1;
    }}

    #input-field:focus {{
        border: none;
    }}

    #timer-label {{
        color: {LIGHTBLUE};
        padding: 0 1;
    }}

    #count-label {{
        color: {MUTEDBLUE};
        padding: 0 1;
    }}

    #clear-btn {{
        background: {MIDBLUE};
        color: {TEXT};
        min-width: 8;
        height: 3;
        margin: 0 1;
    }}

    #input-label {{
        color: {LIGHTBLUE};
        padding: 0 1;
        height: 3;
        content-align: center middle;
    }}

    #thinking-bar {{
        background: #1e293b;
        height: 1;
        padding: 0 2;
        dock: bottom;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_view", "Clear"),
        Binding("ctrl+d", "quit", "Quit"),
    ]

    # ── State ──────────────────────────────────────────────────────
    _last_input_time: float
    _msg_count: int
    _thinking: bool
    _session_start: float
    _conversation_history: list
    _processing: bool

    # Agent components (initialized in _init_agent)
    _memory_store = None
    _skills_lib = None
    _provider = None
    _plugin_callables = None
    _plugin_schemas = None
    _mcp_manager = None
    _config = None
    _agent_ready: bool = False

    def __init__(self):
        super().__init__()
        self._last_input_time = time.time()
        self._msg_count = 0
        self._thinking = False
        self._session_start = time.time()
        self._conversation_history = []
        self._processing = False
        self._agent_ready = False

    # ── Compose UI ─────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="conversation", highlight=True, markup=True, wrap=True)
        with Horizontal(id="input-bar"):
            yield Input(id="input-field", placeholder="❯ Type your message…")
            yield Button("Clear", id="clear-btn", variant="primary")
        yield Static(id="status-bar")

    def on_mount(self) -> None:
        self.query_one("#input-field", Input).focus()
        self.set_interval(1, self._update_status_bar)
        self._update_status_bar()
        self._init_agent()

    def _update_status_bar(self) -> None:
        try:
            elapsed = time.time() - self._last_input_time
            timer = _fmt_time(elapsed)
            status = self.query_one("#status-bar", Static)
            thinking = " 🤖 Thinking…" if self._thinking else ""
            status.update(f"💬 {self._msg_count}  ⏱ {timer}{thinking}")
        except Exception:
            pass  # Gracefully handle shutdown races

    # ── Agent initialization ─────────────────────────────────────────
    def _init_agent(self) -> None:
        """Load config, models, memory, plugins — runs in worker thread."""
        self._run_init_worker()

    @work(thread=True, exit_on_error=False)
    def _run_init_worker(self) -> None:
        try:
            from agent import load_config
            from memory import MemoryStore
            from skills import SkillLibrary
            from provider import ZenProvider
            from mcp_client import MCPManager
            from plugins import load_plugins

            config = load_config()

            # Resolve relative paths
            _cfg_dir = os.path.dirname(os.path.abspath(config.get("_config_path", "config.json")))
            for _key in ("memory_db", "skills_db"):
                _val = config.get(_key)
                if _val and not os.path.isabs(_val):
                    config[_key] = os.path.join(_cfg_dir, _val)

            zen_api_key = os.environ.get("ZEN_API_KEY") or config.get("zen_api_key", "")
            if not zen_api_key or zen_api_key == "REPLACE_WITH_YOUR_ZEN_KEY":
                self._safe_warning(
                    "⚠️  No ZEN_API_KEY set.\nSet ZEN_API_KEY env var or configure zen_api_key in config.json")
                self._agent_ready = True
                return

            memory_store = MemoryStore(config.get("memory_db", "agent_memory.db"))
            skills_lib = SkillLibrary(config.get("skills_db", "agent_skills.db"))
            provider = ZenProvider(
                api_key=zen_api_key,
                base_url=config.get("zen_base_url", "https://api.zenprovider.com/v1"),
                model=config.get("zen_model", "gpt-4o"),
            )

            # Load plugins
            plugin_callables, plugin_schemas = load_plugins()

            # MCP
            mcp_servers = {k: v for k, v in config.get("mcp_servers", {}).items() if not k.startswith("_")}
            mcp_manager = MCPManager(mcp_servers)
            mcp_manager._ensure_connected()

            self._config = config
            self._memory_store = memory_store
            self._skills_lib = skills_lib
            self._provider = provider
            self._plugin_callables = plugin_callables
            self._plugin_schemas = plugin_schemas
            self._mcp_manager = mcp_manager
            self._agent_ready = True

            self.call_from_thread(self._load_history)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._safe_warning(
                f"⚠️  Agent init failed: {e}\n\n{tb[-500:]}")

    def _safe_warning(self, msg: str) -> None:
        """Show warning from a worker thread if the app is still running."""
        try:
            self.call_from_thread(self._show_warning, msg)
        except Exception:
            pass  # App may have been closed during init

    def _show_warning(self, msg: str) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(Panel(Text(msg, style=f"bold {YELLOW}"), style=RichStyle(color=YELLOW)))

    # ── History persistence ─────────────────────────────────────────
    def _load_history(self) -> None:
        if not self._memory_store:
            return
        try:
            entries = self._memory_store.recent(n=20)
            for entry in reversed(entries):
                if entry.user_input:
                    self._append_msg("user", entry.user_input, entry.timestamp)
                if entry.agent_output:
                    self._append_msg("agent", entry.agent_output, entry.timestamp)
        except Exception:
            pass

    # ── Message display ─────────────────────────────────────────────
    def _append_msg(self, role: str, text: str, ts: str | None = None) -> None:
        stamp = ts or _fmt_ts()
        log = self.query_one("#conversation", RichLog)
        if role == "user":
            panel = Panel(
                Text(f"🧑 {text}", style=f"bold {LIGHTBLUE}"),
                style=RichStyle(color=MUTEDBLUE),
                subtitle=Text(f" {stamp} ", style=f"italic {MUTEDBLUE}"),
                subtitle_align="right",
            )
        else:
            panel = Panel(
                Markdown(text),
                style=RichStyle(color=TEXT),
                subtitle=Text(f" {stamp} ", style=f"italic {MUTEDBLUE}"),
                subtitle_align="right",
            )
        log.write(panel)
        self._msg_count += 1

    def user_input(self, text: str) -> None:
        """Called by run_turn — display user message."""
        self.call_from_thread(self._append_msg, "user", text)

    def assistant(self, content: str) -> None:
        """Called by run_turn — display agent response."""
        self.call_from_thread(self._append_msg, "agent", content)

    def reasoning(self, text: str) -> None:
        """Called by run_turn — show chain-of-thought."""
        stamp = _fmt_ts()
        log = self.query_one("#conversation", RichLog)
        panel = Panel(
            Text(f"🤔 {text}", style=f"italic {YELLOW}"),
            style=RichStyle(color=YELLOW),
            subtitle=Text(f" {stamp} ", style=f"italic {MUTEDBLUE}"),
            subtitle_align="right",
        )
        log.write(panel)

    def tool_call(self, name: str, args_preview: str = "",
                  tool_call_id: str = "") -> None:
        """Called by run_turn — show tool call."""
        log = self.query_one("#conversation", RichLog)
        preview = args_preview[:120] + "…" if len(args_preview) > 120 else args_preview
        log.write(Text(f"  🔧 {name}({preview})", style=f"bold {MIDBLUE}"))

    def tool_start(self, name: str, args_preview: str = "") -> None:
        self.tool_call(name, args_preview)

    def tool_end(self, name: str, result: str = "", duration: float = 0,
                 ok: bool = True) -> None:
        log = self.query_one("#conversation", RichLog)
        status = "✅" if ok else "❌"
        result_preview = result[:200].replace("\n", " ") + ("…" if len(result) > 200 else "")
        log.write(Text(f"  {status} {name} ({duration:.1f}s): {result_preview}",
                       style=RichStyle(color=GREEN if ok else RED)))

    def tool_batch(self, results: list[dict]) -> None:
        log = self.query_one("#conversation", RichLog)
        for r in results:
            name = r.get("name", r.get("tool_call_id", "?"))
            ok = r.get("ok", True)
            dur = r.get("duration", 0)
            status = "✅" if ok else "❌"
            log.write(Text(f"  {status} {name} ({dur:.1f}s)",
                          style=RichStyle(color=GREEN if ok else RED)))

    def recall_header(self) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(Text("\n📚 Context retrieved:", style=f"bold {LIGHTBLUE}"))

    def context_hit(self, source: str, snippet: str, score: float) -> None:
        log = self.query_one("#conversation", RichLog)
        snippet_short = snippet[:100].replace("\n", " ") + ("…" if len(snippet) > 100 else "")
        log.write(Text(f"  [{source}] ({score:.2f}) {snippet_short}",
                      style=RichStyle(color=MUTEDBLUE)))

    def separator(self) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(Text("─" * 40, style=RichStyle(color=MIDBLUE)))

    def turn_start(self, query: str, **kwargs) -> None:
        self._thinking = True
        self._update_status_bar()

    def turn_end(self) -> None:
        self._thinking = False
        self._update_status_bar()

    def clear_screen(self) -> None:
        log = self.query_one("#conversation", RichLog)
        log.clear()

    def set_verbose_tool_output(self, verbose: bool) -> None:
        pass  # Not needed in Textual version

    def learned_skill(self, name: str) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(Text(f"  🧠 Learned skill: {name}", style=f"bold {GREEN}"))

    # ── Input handling ──────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text or self._processing:
            return

        event.input.value = ""
        self._last_input_time = time.time()
        self._processing = True

        # Show user message immediately
        self._append_msg("user", user_text)

        # Run agent turn in worker
        self._run_turn_worker(user_text)

    @work(thread=True, exit_on_error=False)
    def _run_turn_worker(self, user_text: str) -> None:
        if not self._agent_ready or not self._provider:
            self.call_from_thread(self._append_msg, "agent",
                                  "*Agent not ready. Check ZEN_API_KEY configuration.*")
            self._processing = False
            return

        from agent import run_turn

        self.call_from_thread(self.turn_start, user_text)

        try:
            response, history = run_turn(
                provider=self._provider,
                user_input=user_text,
                memory_store=self._memory_store,
                skills_lib=self._skills_lib,
                plugin_callables=self._plugin_callables,
                plugin_schemas=self._plugin_schemas,
                mcp_manager=self._mcp_manager,
                config=self._config,
                tui=self,
                conversation_history=self._conversation_history,
            )
            self._conversation_history = history

            self.call_from_thread(self.assistant, response)

        except Exception as exc:
            self.call_from_thread(self._append_msg, "agent",
                                  f"*Error: {exc}*")

        self.call_from_thread(self.turn_end)
        self._processing = False

    # ── Button / Key handlers ───────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clear-btn":
            self.clear_screen()

    def action_clear_view(self) -> None:
        self.clear_screen()

    # ── Quit ────────────────────────────────────────────────────────
    def on_exit(self) -> None:
        if self._mcp_manager:
            try:
                self._mcp_manager.stop_all()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    app = ElingTextualTUI()
    app.run()


if __name__ == "__main__":
    main()
