#!/usr/bin/env python3
"""
Eling TUI — terminal display inspired by Hermes (rich panels, banner,
skin-aware colors) and Zero (sticky plan panel with step status, progress
tracking, timings). Zero-dependency beyond Rich and the stdlib.

Usage:
    from tui import ElingTUI
    tui = ElingTUI()
    tui.banner(skills=3, memories=5, plugins=2, mcp=1)
    tui.user_input("how do I list files")
    tui.assistant("Use os.listdir()...")
    tui.tool_call("run_shell", "ls -la", 0.3, ok=True)
    tui.plan_update([{"content": "Analyze", "status": "completed", ...}, ...])
    tui.learned_skill("list-files")
"""
from contextlib import contextmanager
from pathlib import Path
import os
import threading
import itertools
import time
from datetime import datetime
from typing import Optional

from rich.panel import Panel
from rich.markdown import Markdown
from rich.markup import escape
from rich.syntax import Syntax
from rich.console import Console
from rich.rule import Rule
from rich import box
from rich.console import Group
from rich.style import Style as RichStyle

# ── Formatting helpers ─────────────────────────────────────────────────

def format_time(seconds: float) -> str:
    """Format seconds into human-readable time (e.g. 90 → 1m30s)."""
    dur = int(seconds)
    hours, rem = divmod(dur, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


# ── Read version from pyproject.toml ──────────────────────────────────

_ROOT = Path(__file__).resolve().parent


def _get_version() -> str:
    """Read version from .agent-version or pyproject.toml, in that order."""
    try:
        # Agent CLI version marker wins if present
        ver_file = _ROOT / ".agent-version"
        if ver_file.exists():
            v = ver_file.read_text().strip()
            if v:
                return v
        # Fall back to pyproject.toml
        pyproject = _ROOT / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text().splitlines():
                if line.startswith("version ="):
                    return line.split("=")[1].strip().strip('"')
    except Exception:
        pass
    return "0.1.0"


VERSION = _get_version()

# ── Color palette system ────────────────────────────────────────────
# Design master:   more important UI = lighter / higher-contrast color
#   DEEPBLUE  → lowest  importance (footers, muted backgrounds)
#   MUTEDBLUE → low     importance (timestamps, metadata)
#   LIGHTBLUE → medium  importance (borders, tertiary accents)
#   MIDBLUE   → high    importance (secondary highlights, progress)
#   ACCENT    → highest importance (headers, key highlights, model name)
#   TEXT      → body copy (always lightest for readability)
# Each theme maps its color family across the 5-tier importance scale.
THEMES: dict[str, dict[str, str]] = {
    "blue": {
        "ACCENT": "#60a5fa",
        "MIDBLUE": "#3b82f6",
        "LIGHTBLUE": "#93c5fd",
        "MUTEDBLUE": "#bfdbfe",
        "DEEPBLUE": "#1e3a5f",
        "TEXT": "#f0f9ff",
        "GREEN": "#22c55e",
        "RED": "#ef4444",
    },
    "pink": {
        "ACCENT": "#ff89a3",
        "MIDBLUE": "#ff69b4",
        "LIGHTBLUE": "#ffb6c1",
        "MUTEDBLUE": "#ffc0cb",
        "DEEPBLUE": "#6b2142",
        "TEXT": "#fff5f7",
        "GREEN": "#7dcea0",
        "RED": "#e74c6f",
    },
    "green": {
        "ACCENT": "#6ee7b7",
        "MIDBLUE": "#34d399",
        "LIGHTBLUE": "#a7f3d0",
        "MUTEDBLUE": "#d1fae5",
        "DEEPBLUE": "#1a3a2a",
        "TEXT": "#f0fdf4",
        "GREEN": "#6ee7b7",
        "RED": "#fca5a5",
    },
    "yellow": {
        "ACCENT": "#fde047",
        "MIDBLUE": "#facc15",
        "LIGHTBLUE": "#fef08a",
        "MUTEDBLUE": "#fef9c3",
        "DEEPBLUE": "#5c4a00",
        "TEXT": "#fffef5",
        "GREEN": "#86efac",
        "RED": "#f87171",
    },
    "red": {
        "ACCENT": "#f87171",
        "MIDBLUE": "#ef4444",
        "LIGHTBLUE": "#fca5a5",
        "MUTEDBLUE": "#fecaca",
        "DEEPBLUE": "#5c1515",
        "TEXT": "#fff5f5",
        "GREEN": "#6ee7b7",
        "RED": "#f87171",
    },
    "white": {
        "ACCENT": "#e2e8f0",
        "MIDBLUE": "#cbd5e1",
        "LIGHTBLUE": "#f1f5f9",
        "MUTEDBLUE": "#f8fafc",
        "DEEPBLUE": "#334155",
        "TEXT": "#f8fafc",
        "GREEN": "#86efac",
        "RED": "#fca5a5",
    },
    "ocean": {
        "ACCENT": "#22d3ee",
        "MIDBLUE": "#06b6d4",
        "LIGHTBLUE": "#67e8f9",
        "MUTEDBLUE": "#a5f3fc",
        "DEEPBLUE": "#083344",
        "TEXT": "#f0f9ff",
        "GREEN": "#2a9d8f",
        "RED": "#e76f51",
    },
    "twilight": {
        "ACCENT": "#a78bfa",
        "MIDBLUE": "#8b5cf6",
        "LIGHTBLUE": "#c4b5fd",
        "MUTEDBLUE": "#ddd6fe",
        "DEEPBLUE": "#2e1065",
        "TEXT": "#f5f3ff",
        "GREEN": "#86efac",
        "RED": "#fca5a5",
    },
    "pastel": {
        "ACCENT": "#b8c0ff",
        "MIDBLUE": "#c8b6ff",
        "LIGHTBLUE": "#e2d5ff",
        "MUTEDBLUE": "#f0eaff",
        "DEEPBLUE": "#5b4a7a",
        "TEXT": "#faf5ff",
        "GREEN": "#a3c9b7",
        "RED": "#e2a6a6",
    },
    "brown": {
        "ACCENT": "#d4a574",
        "MIDBLUE": "#c28a5c",
        "LIGHTBLUE": "#e8c9a0",
        "MUTEDBLUE": "#f0dcc0",
        "DEEPBLUE": "#4a3220",
        "TEXT": "#fdf6ed",
        "GREEN": "#7dcea0",
        "RED": "#e67e5a",
    },
    "cobalt": {
        "ACCENT": "#93c5fd",
        "MIDBLUE": "#60a5fa",
        "LIGHTBLUE": "#bfdbfe",
        "MUTEDBLUE": "#dbeafe",
        "DEEPBLUE": "#1e3a5f",
        "TEXT": "#f0f9ff",
        "GREEN": "#22c55e",
        "RED": "#ef4444",
    },
}

DEFAULT_THEME = "cobalt"

_THEME_NAMES = list(THEMES.keys())

def _resolve_theme_name(name: str | None) -> str:
    """Resolve a theme name; 'auto' rotates per session (each /new picks a new theme)."""
    if name == "auto":
        import time
        return _THEME_NAMES[int(time.time()) % len(_THEME_NAMES)]
    return name if name in THEMES else DEFAULT_THEME

# Resolve a theme by name, falling back to default on unknown names.
def _resolve_theme(name: str | None) -> dict[str, str]:
    return THEMES[_resolve_theme_name(name)]

# Module-level convenience references (used by code that imports tui.ACCENT etc.)
_ACTIVE_THEME = _resolve_theme(DEFAULT_THEME)
ACCENT = _ACTIVE_THEME["ACCENT"]
MIDBLUE = _ACTIVE_THEME["MIDBLUE"]
LIGHTBLUE = _ACTIVE_THEME["LIGHTBLUE"]
MUTEDBLUE = _ACTIVE_THEME["MUTEDBLUE"]
DEEPBLUE = _ACTIVE_THEME["DEEPBLUE"]
TEXT = _ACTIVE_THEME["TEXT"]
GREEN = _ACTIVE_THEME["GREEN"]
RED = _ACTIVE_THEME["RED"]

# ── Status icons ─────────────────────────────────────────────────────
ICON_PENDING = "○"
ICON_IN_PROGRESS = "⟳"
ICON_COMPLETED = "✓"
ICON_FAILED = "✗"

# ── Banner art (wordmark-style "ELING") ────────────────────────────────
BANNER = [
    "  ███████╗██╗     ██╗███╗   ██╗ ██████╗ ",
    "  ██╔════╝██║     ██║████╗  ██║██╔════╝ ",
    "  █████╗  ██║     ██║██╔██╗ ██║██║  ███╗",
    "  ██╔══╝  ██║     ██║██║╚██╗██║██║   ██║",
    "  ███████╗███████╗██║██║ ╚████║╚██████╔╝",
    "  ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝ ╚═════╝ ",
]


class ElingTUI:
    """Eling's terminal display — Rich-powered REPL with plan panel."""

    def __init__(self, compact: bool = False, session_start: float | None = None,
                 theme: str | None = None):
        self.console = Console()
        self.compact = compact
        self._plan_steps: list[dict] = []
        self._plan_started: Optional[float] = None
        self._step_started: dict[int, float] = {}
        self._step_completed: dict[int, float] = {}
        self._interactive = False

        # Resolve theme
        self._theme_name = _resolve_theme_name(theme)
        pal = _resolve_theme(theme)
        self.MUTEDBLUE = pal["MUTEDBLUE"]
        self.ACCENT = pal["ACCENT"]
        self.GREEN = pal["GREEN"]
        self.RED = pal["RED"]
        self.MIDBLUE = pal["MIDBLUE"]
        self.LIGHTBLUE = pal["LIGHTBLUE"]
        self.DEEPBLUE = pal["DEEPBLUE"]
        self.TEXT = pal["TEXT"]

        self.session_start = session_start if session_start is not None else time.time()
        self._turn_start = None
        self._verbose_tool_output = True  # can be overridden via set_verbose()

        # Override Rich's default markdown colors (magenta defaults → blue)
        from rich.theme import Theme
        self.console.push_theme(Theme({
            'markdown.h1': RichStyle(bold=True, color=self.LIGHTBLUE),
            'markdown.h2': RichStyle(underline=True, color=self.LIGHTBLUE),
            'markdown.h3': RichStyle(bold=True, color=self.LIGHTBLUE),
            'markdown.h4': RichStyle(italic=True, color=self.LIGHTBLUE),
            'markdown.h5': RichStyle(italic=True, color=self.LIGHTBLUE),
            'markdown.h6': RichStyle(dim=True, color=self.LIGHTBLUE),
            'markdown.code': RichStyle(color=self.MIDBLUE),
            'markdown.code_block': RichStyle(color=self.MIDBLUE),
            'markdown.list': RichStyle(color=self.LIGHTBLUE),
            'markdown.link': RichStyle(color=self.LIGHTBLUE),
            'markdown.link_url': RichStyle(color=self.LIGHTBLUE),
            'markdown.strong': RichStyle(color=self.TEXT),
            'markdown.emphasis': RichStyle(italic=True, color=self.LIGHTBLUE),
            'markdown.text': RichStyle(color=self.TEXT),
            'markdown.paragraph': RichStyle(color=self.TEXT),
            'markdown.table.border': RichStyle(color=self.LIGHTBLUE),
            'markdown.table.header': RichStyle(bold=True, color=self.TEXT),
        }))

    # ── Thinking indicator (scroll-safe heartbeat) ─────────────────

    _thinking_start_time: float | None = None

    def working_info(self, message: str):
        """Print a progress line below the working header.

        Call this during ``thinking()`` context to show updates
        (tool calls, context hits, etc.). Each call appends a new
        line to the terminal so scrollback is preserved.
        """
        elapsed = format_time(time.time() - self._thinking_start_time) if self._thinking_start_time else "0s"
        self.console.print(f"  [{self.MUTEDBLUE}]┃ {message}  ⏱ {elapsed}[/]")

    @contextmanager
    def thinking(self, message: str = ""):
        """Show a working indicator with a scroll-safe heartbeat.

        Prints a ``🤖 Working…`` line at the start, then appends a
        new heartbeat line every 3 seconds with an animated spinner
        character and live elapsed time. Each line is a new terminal
        line so scrollback is preserved. Ends with ``✅ Done``.
        """
        if self._turn_start is None:
            self._turn_start = time.time()
        self._thinking_start_time = time.time()

        stop_event = threading.Event()
        spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])

        def _heartbeat():
            while not stop_event.wait(3):
                elapsed = format_time(time.time() - self._thinking_start_time)
                frame = next(spinner)
                self.console.print(
                    f"  [{self.MUTEDBLUE}]{frame} Working…  ⏱ {elapsed}[/]"
                )

        thread = threading.Thread(target=_heartbeat, daemon=True)
        thread.start()

        self.console.print(f"  [bold {self.ACCENT}]🤖 Working…[/]  [bold {self.MIDBLUE}]⏱ 0s[/]")
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            elapsed = format_time(time.time() - self._thinking_start_time)
            self.console.print(f"  [{self.GREEN}]✅ Done[/]  [{self.MUTEDBLUE}]⏱ {elapsed}[/]")
            self._thinking_start_time = None

    def session_duration(self) -> str:
        """Return human-readable session uptime."""
        dur = time.time() - self.session_start
        hours, rem = divmod(int(dur), 3600)
        mins, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {mins}m {secs}s"
        if mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"

    # ── Banner (Hermes-inspired) ──────────────────────────────────────

    def banner(
        self,
        skills: int = 0,
        memories: int = 0,
        plugins: int = 0,
        mcp: int = 0,
        model: str = "",
        theme: str = "",
    ):
        """Print startup banner with logo on top, features below."""
        lines = list(BANNER)  # ELING wordmark
        lines.append(f"[dim {self.MUTEDBLUE}]Eling v{VERSION} — Auto-Learning Agent[/]")
        lines.append("")

        stats = []
        if plugins:
            stats.append(f"[{self.TEXT}]{plugins} plugins[/]")
        if mcp:
            stats.append(f"[{self.TEXT}]{mcp} MCP servers[/]")
        if skills:
            stats.append(f"[{self.TEXT}]{skills} skills[/]")
        if memories:
            stats.append(f"[{self.TEXT}]{memories} memories[/]")
        if model:
            short = model.split("/")[-1] if "/" in model else model
            pretty = short.replace("-", " ").title()
            lines.append(f"[bold {self.ACCENT}]🤖 {pretty}[/]")
        if stats:
            lines.append(f"[dim {self.MUTEDBLUE}]{' · '.join(stats)}[/]")
        if theme:
            lines.append(f"[dim {self.LIGHTBLUE}]🎨 {theme}[/]")

        lines.append(f"[bold {self.MIDBLUE}]⏱ Startup time: {self.session_duration()}[/]")

        content = "\n".join(lines)
        self.console.print()
        self.console.print(
            Panel(content, box=box.ROUNDED, border_style=self.LIGHTBLUE, padding=(1, 2))
        )
        self.console.print()

    # ── Plan Panel (Zero-inspired sticky plan) ────────────────────────

    def plan_update(self, items: list[dict]):
        """Update the plan panel with new step items.

        Each item: {"content": str, "status": "pending"|"in_progress"|"completed"|"failed",
                    "notes"?: str}
        Matches by content to preserve start/completion timestamps (Zero-style).
        """
        now = time.time()
        if self._plan_started is None and items:
            self._plan_started = now

        # Build new steps, preserving timestamps from previous by content match
        prev_steps = {
            s["content"]: s for s in self._plan_steps
        }
        new_steps = []
        for i, item in enumerate(items):
            content = item["content"]
            status = item["status"]
            prev = prev_steps.get(content, {})

            if status == "in_progress" and not prev.get("started"):
                prev["started"] = now
            if status in ("completed", "failed") and not prev.get("completed"):
                prev["completed"] = now
            if status in ("pending",):
                if prev.get("completed"):
                    prev["completed"] = None  # reset on re-pending

            new_steps.append({
                "content": content,
                "status": status,
                "notes": item.get("notes", ""),
                "started": prev.get("started"),
                "completed": prev.get("completed") if status in (
                    "completed", "failed") else None,
            })

        self._plan_steps = new_steps
        self._render_plan()

    def _render_plan(self):
        """Render the plan panel if steps exist."""
        steps = self._plan_steps
        if not steps:
            return

        total = len(steps)
        done = sum(1 for s in steps if s["status"] in ("completed", "failed"))
        pct = done / total if total else 0

        # Steps
        bar_width = 20
        filled = int(bar_width * pct)
        lines = [""]
        lines.append(
            f"  [bold {self.ACCENT}]📋 Plan[/]  "
            f"[{self.MUTEDBLUE}]·  Step {done}/{total}[/]  "
            f"[{self.LIGHTBLUE}]{'█' * filled}{'░' * (bar_width - filled)}[/]"
        )
        for i, s in enumerate(steps):
            icon = {
                "pending": f"[{self.MUTEDBLUE}]{ICON_PENDING}[/]",
                "in_progress": f"[{self.DEEPBLUE}]{ICON_IN_PROGRESS}[/]",
                "completed": f"[{self.GREEN}]{ICON_COMPLETED}[/]",
                "failed": f"[{self.RED}]{ICON_FAILED}[/]",
            }.get(s["status"], ICON_PENDING)

            elapsed = ""
            if s["started"] and s["status"] == "in_progress":
                dur = time.time() - s["started"]
                elapsed = f"  [{self.MUTEDBLUE}]{dur:.1f}s[/]"
            elif s["started"] and s["completed"]:
                dur = s["completed"] - s["started"]
                elapsed = f"  [{self.MUTEDBLUE}]{dur:.1f}s[/]"

            content = s["content"]
            if len(content) > 60:
                content = content[:57] + "..."

            note = ""
            if s["notes"]:
                note = f"\n    [{self.MUTEDBLUE}]↳ {s['notes']}[/]"

            lines.append(f"    {icon}  [{self.TEXT}]{content}[/]{elapsed}{note}")

        panel_content = "\n".join(lines)
        self.console.print(
            Panel(
                panel_content,
                box=box.SQUARE,
                border_style=self.MUTEDBLUE,
                padding=(0, 1),
            )
        )

    def plan_clear(self):
        """Clear the plan panel."""
        self._plan_steps = []
        self._plan_started = None
        self._step_started = {}
        self._step_completed = {}

    # ── User Input (Hermes-style) ─────────────────────────────────────

    def user_input(self, text: str):
        """Print user input with a styled prompt and session timer."""
        ts = datetime.now().strftime("%H:%M:%S")
        dur = self.session_duration()
        self.console.print(f"[dim {self.MUTEDBLUE}]{ts}[/]  [bold {self.ACCENT}]┃[/]  [{self.TEXT}]{escape(text)}[/]  [dim {self.MUTEDBLUE}]⏱ {dur}[/]")
        self.console.print()

    # ── Assistant Response (spacious, single-border) ────────────────

    def assistant(self, content: str):
        """Render assistant response — code-aware with single blue border."""
        ts = datetime.now().strftime("%H:%M:%S")
        dur = self.session_duration()

        has_code = "```" in content

        if has_code:
            parts = content.split("```")
            renders = []
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    if part.strip():
                        renders.append(Markdown(part.strip()))
                        renders.append("")
                else:
                    lines = part.split("\n", 1)
                    lang = lines[0].strip() if lines else ""
                    code = lines[1] if len(lines) > 1 else ""
                    if not code.strip():
                        code = lang
                        lang = ""
                    renders.append(
                        Syntax(code, lang or "text", theme="monokai",
                               background_color="default",
                               line_numbers=True, word_wrap=True)
                    )
                    renders.append("")
            # Remove trailing empty string if content ends with code
            if renders and renders[-1] == "":
                renders.pop()
            body = Group(*renders)
            body = Group(*renders)
            title_str = "[bold white]Eling[/]"
        else:
            body = Markdown(content)
            title_str = "[bold white]Eling[/]"

        self.console.print(
            Panel(
                body,
                title=title_str,
                subtitle=f"[dim {self.LIGHTBLUE}]{ts}  ⏱ {dur}[/]",
                box=box.ROUNDED,
                border_style=self.LIGHTBLUE,
                padding=(1, 2),
            )
        )
        self.console.print()

    # ── Reasoning (expanded, spacious) ──────────────────────────────

    def reasoning(self, text: str):
        """Display model reasoning in a spacious panel with more context."""
        if not text or not text.strip():
            return
        lines = text.strip().splitlines()
        # Show up to 30 lines
        display = "\n".join(lines[:30])
        if len(lines) > 30:
            display += f"\n  [{self.MUTEDBLUE}]... and {len(lines) - 30} more lines[/]"
        if len(display) > 3000:
            display = display[:2997] + "..."
        self.console.print(
            Panel(
                f"[{self.MUTEDBLUE}]{escape(display)}[/]",
                title=f"[bold {self.MIDBLUE}]🤔 Reasoning[/]",
                box=box.ROUNDED,
                border_style=self.LIGHTBLUE,
                padding=(1, 1),
            )
        )
        self.console.print()

    # ── Tool Call (verbose, spacious) ───────────────────────────────

    def tool_call(self, name: str, args_preview: str = "",
                  duration: float = 0, ok: bool = True,
                  _result: str = ""):
        """Display a single tool execution in a spacious panel with full output."""
        status = f"[{self.GREEN}]Success[/]" if ok else f"[{self.RED}]Failed[/]"
        dur_str = f"[{self.MUTEDBLUE}]{duration:.1f}s[/]" if duration else "[{self.MUTEDBLUE}]—[/]"

        lines = [f"  [{self.TEXT}]⚙ Tool: [bold {self.ACCENT}]{name}[/][/]"]
        if args_preview:
            lines.append(f"  [{self.MUTEDBLUE}]  Args: {args_preview}[/]")
        lines.append(f"  [{self.MUTEDBLUE}]  Result: {status}  ⏱ {dur_str}[/]")

        if _result:
            if not self._verbose_tool_output and len(_result) > 120:
                _result = _result[:117] + "..."
            # Show full output with syntax highlighting (or compact if verbose disabled)
            lang = "python" if (_result.startswith(("import ", "def ", "class ", "print(", "for ", "if ", "return ", "from ")) and "\n" in _result) else "text"
            lines.append(Syntax(_result, lang, theme="monokai", background_color="default", word_wrap=True))

        self.console.print(
            Panel(
                Group(*lines),
                border_style=self.MIDBLUE,
                padding=(1, 1),
                box=box.ROUNDED,
            )
        )
        self.console.print()

    # ── Tool Start / End (thin wrappers for full-verbosity flow) ───

    def set_verbose_tool_output(self, verbose: bool):
        """Enable/disable full-verbosity tool output.

        When disabled, long tool results are truncated to 120 characters
        instead of rendered in full with syntax highlighting.
        """
        self._verbose_tool_output = verbose

    def tool_start(self, name: str, args_preview: str = ""):
        """Called before tool execution — lightweight one-liner with full command.

        Prints the tool name and full argument preview immediately, so the user
        sees what's being dispatched without waiting for the result panel.
        """
        self.console.print(f"  [{self.MIDBLUE}]▶ Running [bold {self.ACCENT}]{name}[/][/]")
        if args_preview:
            lang = "bash" if any(kw in name.lower() for kw in ("shell", "term", "bash", "exec")) else "text"
            self.console.print(
                Syntax(args_preview, lang, theme="monokai", word_wrap=True, background_color="default")
            )

    def tool_end(self, name: str, result: str = "", duration: float = 0, ok: bool = True):
        """Called after tool execution — shows the full, untruncated output result."""
        self.tool_call(name, duration=duration, ok=ok, _result=result)

    def tool_batch(self, results: list[dict]):
        """Display parallel tool results in a spacious multi-line panel."""
        items = []
        for r in results:
            name = r.get("name", "?")
            dur = r.get("duration", 0)
            ok = r.get("ok", True)
            icon = f"[{self.GREEN}]✓[/]" if ok else f"[{self.RED}]✗[/]"
            dur_str = f"[{self.MUTEDBLUE}]{dur:.1f}s[/]" if dur else ""
            items.append(f"  {icon}  [{self.TEXT}]{name}[/]  {dur_str}")

        if items:
            content = "\n".join(items)
            self.console.print(
                Panel(
                    f"\n{content}\n",
                    title=f"[bold {self.ACCENT}]⚡ Parallel Calls[/]",
                    border_style=self.LIGHTBLUE,
                    padding=(0, 1),
                    box=box.ROUNDED,
                )
            )
            self.console.print()

    # ── Context Retrieval (spacious, verbose) ─────────────────────────

    def context_hit(self, source: str, snippet: str, score: float):
        """Show a context retrieval hit with expanded detail."""
        short = snippet[:2000] + "..." if len(snippet) > 2000 else snippet
        color = self.GREEN if score > 0.5 else (self.MIDBLUE if score > 0.2 else self.MUTEDBLUE)
        self.console.print(
            f"  [{self.MUTEDBLUE}]┃ [{self.ACCENT}]⊞ {source}[/]  "
            f"[{color}]score={score:.2f}[/][/]"
        )
        self.console.print(
            f"  [{self.MUTEDBLUE}]┃   {short}[/]"
        )

    # ── Skill Learning (subtle one-liner) ─────────────────────────────

    def learned_skill(self, name: str):
        """Notify that a skill was auto-learned."""
        self.console.print(
            f"  [{self.MUTEDBLUE}]🧠 Learned skill: [bold {self.ACCENT}]{name}[/][/]"
        )
        self.console.print()

    # ── Separator ──────────────────────────────────────────────────────

    def separator(self):
        """Print a thin rule between turns."""
        self.console.print(Rule(style=MUTEDBLUE))

    # ── Memory recall header ──────────────────────────────────────────

    def recall_header(self):
        """Print spacious header for memory recall."""
        self.console.print(
            Panel(
                f"[bold {self.ACCENT}]⊞ Context Retrieval[/]  "
                f"[{self.MUTEDBLUE}]Searching skills + memories...[/]",
                border_style=self.LIGHTBLUE,
                padding=(0, 1),
                box=box.SQUARE,
            )
        )
        self.console.print()

    # ── Start / end turn ──────────────────────────────────────────────

    def turn_start(self, query: str, **kwargs):
        """Begin a new turn — print user input + separator."""
        self.separator()
        self.user_input(query)

    def turn_end(self):
        """End a turn."""
        self.console.print()

    # ── Clear screen (scrollback-aware, Termux-friendly) ──────────────

    def clear_screen(self):
        """Thorough terminal clear — visible area + scrollback buffer."""
        import sys
        sys.stdout.write("\033[3J\033[2J\033[H")
        sys.stdout.flush()

    # ── Termux-style input prompt with Rich-styled toolbar ────────────

    def input_prompt(self) -> str:
        """Show Termux-style input with persistent history and extra-keys toolbar.

        Uses ``prompt_toolkit`` under the hood (falls back to plain ``input()``
        if the library is unavailable).  The bottom toolbar is styled with the
        same steel-blue palette as the Rich TUI for a cohesive look.
        """
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style
            from prompt_toolkit.formatted_text import FormattedText

            if not hasattr(self, "_pt_session"):
                history_path = os.path.join(
                    os.path.expanduser("~"), ".eling_history"
                )
                kb = KeyBindings()

                # Paste burst detection for Termux char-by-char paste
                _paste_last_time = [0.0]
                _paste_burst = [0]
                _is_termux = "TERMUX_VERSION" in os.environ

                @kb.add("enter")
                def _handle_enter(event):
                    now = time.time()
                    buf = event.current_buffer
                    if _is_termux:
                        gap = now - _paste_last_time[0]
                        if gap < 0.1:
                            _paste_burst[0] += 1
                        else:
                            _paste_burst[0] = 0
                        _paste_last_time[0] = now
                        if _paste_burst[0] > 2:
                            buf.insert_text("\n")
                            return
                    _paste_burst[0] = 0
                    buf.validate_and_handle()

                @kb.add("c-c")
                def _interrupt(event):
                    raise KeyboardInterrupt()

                @kb.add("c-l")
                def _clear_screen(event):
                    event.app.current_buffer.reset()
                    os.system("clear" if os.name == "posix" else "cls")

                style = Style.from_dict({
                    "prompt": f"#{self.ACCENT[1:]} bold",
                    "toolbar": f"#{self.LIGHTBLUE[1:]}",
                    "toolbar.key": f"#{self.ACCENT[1:]} bold",
                    "toolbar.sep": "#525252",
                    "toolbar.info": f"#{self.MUTEDBLUE[1:]}",
                })

                self._pt_session = PromptSession(
                    history=FileHistory(history_path),
                    style=style,
                    key_bindings=kb,
                )

            def _make_toolbar():
                sep = ("class:toolbar.sep", " \u00b7 ")
                dur = self.session_duration()
                return FormattedText([
                    ("class:toolbar.key", " Tab "),
                    ("class:toolbar", "complete"),
                    sep,
                    ("class:toolbar.key", " \u2191\u2193 "),
                    ("class:toolbar", "history"),
                    sep,
                    ("class:toolbar.key", " Esc Enter "),
                    ("class:toolbar", "multi-line"),
                    sep,
                    ("class:toolbar.key", " Ctrl+L "),
                    ("class:toolbar", "clear"),
                    sep,
                    ("class:toolbar.key", " Ctrl+D "),
                    ("class:toolbar", "exit"),
                    ("class:toolbar.sep", "   "),
                    ("class:toolbar.info", f"\u23f1 {dur}"),
                ])

            prompt_text = FormattedText([
                ("class:prompt", " \u276f "),
            ])

            return self._pt_session.prompt(
                prompt_text,
                bottom_toolbar=_make_toolbar,
            )
        except ImportError:
            return input("").strip()
