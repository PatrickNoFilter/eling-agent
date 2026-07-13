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
import time
from datetime import datetime
from typing import Optional

from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Console
from rich.text import Text
from rich.rule import Rule
from rich import box

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

# ── Color palette (steel-blue sequential: eff3ff → 08519c) ───────────
ACCENT = "#3182bd"      # dark blue — headers, highlights
AMBER = "#6baed6"        # medium blue — secondary highlights
BRONZE = "#9ecae1"       # medium-light blue — borders, tertiary
TEXT = "#eff3ff"         # lightest blue — body text (good contrast on dark bg)
DIM = "#c6dbef"          # light blue — muted text, timestamps
GREEN = "#50C878"        # success / completed
RED = "#FF6B6B"          # error / failed
CYAN = "#08519c"         # darkest blue — info / in-progress
PLAN_BORDER = "#6baed6"  # medium blue — session border

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

    def __init__(self, compact: bool = False):
        self.console = Console()
        self.compact = compact
        self._plan_steps: list[dict] = []
        self._plan_started: Optional[float] = None
        self._step_started: dict[int, float] = {}
        self._step_completed: dict[int, float] = {}
        self._interactive = False
        self.DIM = DIM
        self.session_start = time.time()
        self._turn_start = None

        # Override Rich's default markdown heading colors (magenta → green)
        from rich.theme import Theme
        from rich.style import Style as RichStyle
        self.console.push_theme(Theme({
            'markdown.h1': RichStyle(bold=True, color="#90E0EF"),
            'markdown.h2': RichStyle(underline=True, color="#90E0EF"),
            'markdown.h3': RichStyle(bold=True, color="#90E0EF"),
            'markdown.h4': RichStyle(italic=True, color="#90E0EF"),
            'markdown.h5': RichStyle(italic=True, color="#90E0EF"),
            'markdown.h6': RichStyle(dim=True, color="#90E0EF"),
        }))

    # ── Thinking animation ──────────────────────────────────────────

    @contextmanager
    def thinking(self, message: str = ""):
        """Show an animated spinner while processing, with live elapsed counter.

        The elapsed time (since turn_start was called) counts up in real time.
        """
        # Ensure turn timer is running
        if self._turn_start is None:
            self._turn_start = time.time()

        stop_event = threading.Event()

        def _updater(s):
            """Background thread: update status message with live elapsed."""
            while not stop_event.is_set():
                elapsed = time.time() - self._turn_start
                s.update(
                    f"[bold {ACCENT}]🤖 Working[/]  "
                    f"[bold {AMBER}]⏱ {format_time(elapsed)}[/]"
                )
                time.sleep(0.5)

        with self.console.status(
            f"[bold {ACCENT}]🤖 Working[/]  [bold {AMBER}]⏱ 0s[/]",
            spinner="dots12"
        ) as s:
            t = threading.Thread(target=_updater, args=(s,), daemon=True)
            try:
                t.start()
            except RuntimeError:
                pass  # thread already started or can't start
            try:
                yield s
            finally:
                stop_event.set()
                if t.is_alive():
                    t.join(timeout=1.0)

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
    ):
        """Print startup banner with logo on top, features below."""
        lines = list(BANNER)  # ELING wordmark
        lines.append(f"[dim {DIM}]Eling v{VERSION} — Autonomous Agent[/]")
        lines.append("")

        stats = []
        if plugins:
            stats.append(f"[{TEXT}]{plugins} plugins[/]")
        if mcp:
            stats.append(f"[{TEXT}]{mcp} MCP servers[/]")
        if skills:
            stats.append(f"[{TEXT}]{skills} skills[/]")
        if memories:
            stats.append(f"[{TEXT}]{memories} memories[/]")
        if model:
            short = model.split("/")[-1] if "/" in model else model
            # Prettify: deepseek-v4-flash-free → DeepSeek V4 Flash Free
            pretty = short.replace("-", " ").title()
            lines.append(f"[bold {ACCENT}]🤖 {pretty}[/]")
        if stats:
            lines.append(f"[dim {DIM}]{' · '.join(stats)}[/]")

        lines.append(f"[bold {AMBER}]⏱ {self.session_duration()}[/]")

        content = "\n".join(lines)
        self.console.print()
        self.console.print(
            Panel(content, box=box.ROUNDED, border_style=BRONZE, padding=(1, 2))
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

        # Header
        header = Text()
        header.append("  📋 Plan  ", style=f"bold {ACCENT}")
        header.append(f"·  Step {done}/{total}  ", style=DIM)
        # Progress bar (simple ASCII)
        bar_width = 20
        filled = int(bar_width * pct)
        bar = "█" * filled + "░" * (bar_width - filled)
        header.append(f"[{BRONZE}]{bar}[/]  ", style=DIM)

        # Steps
        lines = [""]
        for i, s in enumerate(steps):
            icon = {
                "pending": f"[{DIM}]{ICON_PENDING}[/]",
                "in_progress": f"[{CYAN}]{ICON_IN_PROGRESS}[/]",
                "completed": f"[{GREEN}]{ICON_COMPLETED}[/]",
                "failed": f"[{RED}]{ICON_FAILED}[/]",
            }.get(s["status"], ICON_PENDING)

            elapsed = ""
            if s["started"] and s["status"] == "in_progress":
                dur = time.time() - s["started"]
                elapsed = f"  [{DIM}]{dur:.1f}s[/]"
            elif s["started"] and s["completed"]:
                dur = s["completed"] - s["started"]
                elapsed = f"  [{DIM}]{dur:.1f}s[/]"

            content = s["content"]
            if len(content) > 60:
                content = content[:57] + "..."

            note = ""
            if s["notes"]:
                note = f"\n    [{DIM}]↳ {s['notes']}[/]"

            lines.append(f"    {icon}  [{TEXT}]{content}[/]{elapsed}{note}")

        panel_content = "\n".join(lines)
        self.console.print(
            Panel(
                panel_content,
                box=box.SQUARE,
                border_style=DIM,
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
        self.console.print(f"[dim {DIM}]{ts}[/]  [bold {ACCENT}]┃[/]  [{TEXT}]{text}[/]  [dim {DIM}]⏱ {dur}[/]")
        self.console.print()

    # ── Assistant Response (Hermes-style — Panel with Markdown) ───────

    def assistant(self, content: str):
        """Render assistant response in a panel with Markdown formatting and session timer."""
        ts = datetime.now().strftime("%H:%M:%S")
        dur = self.session_duration()
        md = Markdown(content, code_theme="monokai")
        self.console.print(
            Panel(
                md,
                title=f"[bold {ACCENT}]Eling[/]",
                subtitle=f"[dim {DIM}]{ts}  ⏱ {dur}[/]",
                box=box.ROUNDED,
                border_style=BRONZE,
                padding=(1, 2),
            )
        )
        self.console.print()

    # ── Reasoning (compact, dim — shows model's chain-of-thought) ─────

    def reasoning(self, text: str):
        """Display model reasoning in a compact dim panel."""
        if not text or not text.strip():
            return
        lines = text.strip().splitlines()
        # Trim to first 8 lines for compactness
        if len(lines) > 8:
            lines = lines[:8] + [f"[dim {DIM}]... ({len(lines)-8} more lines)[/]"]
        content = "\n".join(lines)
        self.console.print(
            Panel(
                content,
                title=f"[dim {DIM}]🤔 reasoning[/]",
                box=box.SQUARE,
                border_style=DIM,
                padding=(0, 1),
            )
        )

    # ── Tool Call (Hermes-style, compact) ─────────────────────────────

    def tool_call(self, name: str, args_preview: str = "",
                  duration: float = 0, ok: bool = True):
        """Display a single tool execution result."""
        icon = f"[{GREEN}]✓[/]" if ok else f"[{RED}]✗[/]"
        dur_str = f"  [{DIM}]{duration:.1f}s[/]" if duration else ""
        arg_str = f" [{DIM}]({args_preview})[/]" if args_preview else ""
        self.console.print(
            f"  {icon}  [{TEXT}]⚙ {name}[/]{arg_str}{dur_str}"
        )

    # ── Tool Call Batch (compact view of multiple parallel calls) ─────

    def tool_batch(self, results: list[dict]):
        """Display a set of parallel tool results compactly."""
        lines = []
        for r in results:
            name = r.get("name", "?")
            dur = r.get("duration", 0)
            ok = r.get("ok", True)
            icon = f"[{GREEN}]✓[/]" if ok else f"[{RED}]✗[/]"
            dur_str = f"[{DIM}]{dur:.1f}s[/]" if dur else ""
            lines.append(f"  {icon}  [{TEXT}]{name}[/]  {dur_str}")

        if lines:
            self.console.print("\n".join(lines))

    # ── Context Retrieval (compact, Hermes-style) ─────────────────────

    def context_hit(self, source: str, snippet: str, score: float):
        """Show a context retrieval hit (skill or memory)."""
        short = snippet[:60] + "..." if len(snippet) > 60 else snippet
        self.console.print(
            f"  [{DIM}]▸ [{ACCENT}]{source}[/] "
            f"(score={score:.2f})[/]  [{TEXT}]{short}[/]"
        )

    # ── Skill Learning (subtle one-liner) ─────────────────────────────

    def learned_skill(self, name: str):
        """Notify that a skill was auto-learned."""
        self.console.print(
            f"  [{DIM}]🧠 Learned skill: [bold {ACCENT}]{name}[/][/]"
        )
        self.console.print()

    # ── Separator ──────────────────────────────────────────────────────

    def separator(self):
        """Print a thin rule between turns."""
        self.console.print(Rule(style=DIM))

    # ── Memory recall header ──────────────────────────────────────────

    def recall_header(self):
        """Print compact header for memory recall."""
        self.console.print(f"[dim {DIM}]  ⊞ Recalled context — most relevant[/]")

    # ── Start / end turn ──────────────────────────────────────────────

    def turn_start(self, query: str):
        """Begin a new turn — print user input + separator."""
        self.separator()
        self.user_input(query)

    def turn_end(self):
        """End a turn."""
        self.console.print()
