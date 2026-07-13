"""
Eling library integration plugin — wraps eling's Brain, ContinuumStore,
BlackboxStore, and markdownify as direct Python callables (no MCP subprocess).

Registers the same tool names (brain_*, continuum_*, blackbox_*, markdownify_*)
so existing prompts work transparently.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("eling_integration")

# ── Lazy globals ──────────────────────────────────────────────────────
_brain: Any = None
_continuum: Any = None
_blackbox: Any = None
_markitdown: Any = None


def _get_brain():
    global _brain
    if _brain is None:
        from eling.brain import Brain
        home = os.environ.get("ELING_HOME")
        _brain = Brain(home=Path(home) if home else None)
    return _brain


def _get_continuum():
    global _continuum
    if _continuum is None:
        from eling.continuum.store import ContinuumStore
        _continuum = ContinuumStore()
    return _continuum


def _get_blackbox():
    global _blackbox
    if _blackbox is None:
        from eling.blackbox.store import BlackboxStore
        _blackbox = BlackboxStore()
    return _blackbox


def _get_markitdown():
    global _markitdown
    if _markitdown is None:
        try:
            from markitdown import MarkItDown
            _markitdown = MarkItDown()
        except ImportError:
            pass
    return _markitdown


# ── Helpers ───────────────────────────────────────────────────────────

def _tool(name: str, fn, desc: str, props: dict | None = None,
          required: list[str] | None = None) -> tuple[str, dict]:
    """Build an OpenAI tool entry. Returns (name, {function, description, parameters})."""
    return name, {
        "function": fn,
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": props or {},
            "required": required or [],
        },
    }


def _empty_tool(name: str, fn, desc: str) -> tuple[str, dict]:
    """Tool with no parameters."""
    return name, {
        "function": fn,
        "description": desc,
        "parameters": {"type": "object", "properties": {}},
    }


# ── brain_* tools ─────────────────────────────────────────────────────

def _brain_remember(content: str, layer: str = "auto", category: str = "general",
                    tags: str = "", title: str = "", skip_dedup: bool = False) -> str:
    import json
    result = _get_brain().remember(content=content, layer=layer, category=category,
                                   tags=tags, title=title, skip_dedup=skip_dedup)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_recall(query: str, layers: list[str] | None = None,
                  limit: int = 10, source: str = "") -> str:
    import json
    result = _get_brain().recall(query=query, layers=layers, limit=limit,
                                 source=source or None)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_probe(entity: str, limit: int = 10) -> str:
    import json
    result = _get_brain().probe(entity=entity, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_reason(entities: list[str], limit: int = 10) -> str:
    import json
    result = _get_brain().reason(entities=entities, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_think(query: str, entities: list[str] | None = None, limit: int = 10) -> str:
    import json
    result = _get_brain().think(query=query, entities=entities, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_stats() -> str:
    import json
    result = _get_brain().stats()
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_export(format: str = "json", path: str = "") -> str:
    import json
    result = _get_brain().export(format=format, path=path or None)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_link_stats() -> str:
    import json
    result = _get_brain().link_stats()
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_linked_facts(fact_id: int, limit: int = 10) -> str:
    import json
    result = _get_brain().linked_facts(fact_id=fact_id, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_evolve(threshold: float | None = None) -> str:
    import json
    result = _get_brain().evolve(threshold=threshold)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_snapshot(reason: str = "") -> str:
    import json
    result = _get_brain().snapshot(reason=reason)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_list_snapshots() -> str:
    import json
    result = _get_brain().list_snapshots()
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_rollback(snapshot_id: str) -> str:
    import json
    result = _get_brain().rollback(snapshot_id=snapshot_id)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_search_temporal(query: str, time_start: str = "", time_end: str = "",
                           category: str = "", source: str = "",
                           limit: int = 10) -> str:
    import json
    result = _get_brain().search_temporal(
        query=query,
        time_start=time_start or None,
        time_end=time_end or None,
        category=category or None,
        source=source or None,
        limit=limit,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_verify(status: str = "", command: str = "", output: str = "",
                  spec_check: bool = False,
                  changed_files: list[str] | None = None) -> str:
    import json
    result = _get_brain().verify(status=status, command=command, output=output,
                                 spec_check=spec_check, changed_files=changed_files)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_verify_spec(changed_files: list[str] | None = None) -> str:
    import json
    result = _get_brain().verify_spec(changed_files=changed_files)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_obsidian_search(query: str, limit: int = 10) -> str:
    import json
    ob = _get_brain().obsidian
    if not ob or not ob.available:
        return json.dumps({"error": "Obsidian vault not available"})
    result = ob.search(query=query, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _brain_obsidian_read(path: str) -> str:
    import json
    ob = _get_brain().obsidian
    if not ob or not ob.available:
        return json.dumps({"error": "Obsidian vault not available"})
    result = ob.read(path=path)
    return json.dumps({"content": result} if result else {"error": "File not found"})


def _brain_obsidian_write(path: str, content: str, title: str = "") -> str:
    import json
    ob = _get_brain().obsidian
    if not ob or not ob.available:
        return json.dumps({"error": "Obsidian vault not available"})
    result = ob.write(path=path, content=content,
                      frontmatter={"title": title} if title else None)
    return json.dumps({"path": str(result)} if result else {"error": "Write failed"})


def _brain_obsidian_daily(content: str = "") -> str:
    import json
    ob = _get_brain().obsidian
    if not ob or not ob.available:
        return json.dumps({"error": "Obsidian vault not available"})
    result = ob.daily_note(content=content or None)
    return json.dumps({"path": str(result)} if result else {"error": "Write failed"})


def _brain_obsidian_list(folder: str = "") -> str:
    import json
    ob = _get_brain().obsidian
    if not ob or not ob.available:
        return json.dumps({"error": "Obsidian vault not available"})
    result = ob.list_files(folder=folder)
    return json.dumps(result, ensure_ascii=False, default=str)


# ── continuum_* tools ────────────────────────────────────────────────

def _continuum_project_create(path: str, name: str = "") -> str:
    import json
    result = _get_continuum().project_create(path=path, name=name or None)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_project_get(path: str) -> str:
    import json
    result = _get_continuum().project_get(path=path)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_project_list() -> str:
    import json
    result = _get_continuum().project_list()
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_knowledge_create(project: str, slug: str, content: str,
                                kind: str = "situational", title: str = "") -> str:
    import json
    result = _get_continuum().knowledge_create(
        project=project, slug=slug, content=content, kind=kind, title=title)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_knowledge_get(project: str, slug: str) -> str:
    import json
    result = _get_continuum().knowledge_get(project=project, slug=slug)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_knowledge_list(project: str, kind: str = "") -> str:
    import json
    result = _get_continuum().knowledge_list(project=project, kind=kind or None)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_knowledge_search(project: str, q: str, limit: int = 10) -> str:
    import json
    result = _get_continuum().knowledge_search(project=project, q=q, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_agent_register(project: str, slug: str, branch: str = "",
                               worktree: str = "", prompt: str = "",
                               reserved_paths: list[str] | None = None) -> str:
    import json
    result = _get_continuum().agent_register(
        project=project, slug=slug, branch=branch, worktree=worktree,
        prompt=prompt, reserved_paths=reserved_paths)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_agent_update(project: str, slug: str, status: str = "",
                             branch: str = "", worktree: str = "",
                             prompt: str = "", merged_commit: str = "",
                             reserved_paths: list[str] | None = None) -> str:
    import json
    kwargs: dict[str, Any] = {"project": project, "slug": slug}
    if status:
        kwargs["status"] = status
    if branch:
        kwargs["branch"] = branch
    if worktree:
        kwargs["worktree"] = worktree
    if prompt:
        kwargs["prompt"] = prompt
    if merged_commit:
        kwargs["merged_commit"] = merged_commit
    if reserved_paths is not None:
        kwargs["reserved_paths"] = reserved_paths
    try:
        result = _get_continuum().agent_update(**kwargs)
        return json.dumps(result, ensure_ascii=False, default=str)
    except (KeyError, ValueError) as e:
        return json.dumps({"error": str(e)})


def _continuum_agent_get(project: str, slug: str) -> str:
    import json
    result = _get_continuum().agent_get(project=project, slug=slug)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_registry_list(project: str, status: str = "",
                              limit: int = 50, offset: int = 0) -> str:
    import json
    result = _get_continuum().registry_list(
        project=project, status=status or None, limit=limit, offset=offset)
    return json.dumps(result, ensure_ascii=False, default=str)


def _continuum_plot_get(project: str) -> str:
    import json
    result = _get_continuum().plot_get(project=project)
    return json.dumps({"content": result} if result else {"error": "No PLOT.md found"})


def _continuum_plot_update(project: str, diff: str) -> str:
    import json
    from eling.continuum.plot import apply_unified_diff, seed_plot
    current = _get_continuum().plot_get(project=project)
    if current is None:
        current = seed_plot(project)
        _get_continuum().plot_set(project=project, content=current)
    try:
        updated = apply_unified_diff(current, diff)
        _get_continuum().plot_set(project=project, content=updated)
        return json.dumps({"updated": True})
    except ValueError as e:
        return json.dumps({"error": str(e),
                           "hint": "hunk_mismatch - re-read and regenerate diff"})


def _continuum_reservations(project: str) -> str:
    import json
    result = _get_continuum()._reservation_collisions(
        project, self_slug="", reserved=[])
    return json.dumps(result, ensure_ascii=False, default=str)


# ── blackbox_* tools ─────────────────────────────────────────────────

def _blackbox_stats() -> str:
    import json
    bb = _get_blackbox()
    runs = bb.list_runs(limit=0)
    return json.dumps(
        {"total_runs": len(runs) if isinstance(runs, list) else 0}, default=str)


def _blackbox_runs_list(host: str = "", project_key: str = "", limit: int = 20) -> str:
    import json
    result = _get_blackbox().list_runs(
        host=host or None, project_key=project_key or None, limit=limit)
    return json.dumps(result, ensure_ascii=False, default=str)


def _blackbox_run_get(run_id: str, include_events: bool = False) -> str:
    import json
    result = _get_blackbox().get_run(run_id=run_id)
    if result and include_events:
        result["events"] = _get_blackbox().get_events(run_id=run_id)
    return json.dumps(result, ensure_ascii=False, default=str)


def _blackbox_run_score(run_id: str, archetype: str = "auto") -> str:
    import json
    from eling.blackbox.score import score_run
    result = score_run(store=_get_blackbox(), run_id=run_id, archetype=archetype)
    return json.dumps(result, ensure_ascii=False, default=str)


def _blackbox_run_effectiveness(run_id: str) -> str:
    import json
    from eling.blackbox.effectiveness import score_effectiveness
    result = score_effectiveness(store=_get_blackbox(), run_id=run_id)
    return json.dumps(result, ensure_ascii=False, default=str)


def _blackbox_run_timeline(run_id: str) -> str:
    import json
    from eling.blackbox.timeline import build_timeline
    result = build_timeline(store=_get_blackbox(), run_id=run_id)
    return json.dumps(result, ensure_ascii=False, default=str)


def _blackbox_run_suggest(run_id: str) -> str:
    import json
    result = _get_blackbox().get_run(run_id=run_id)
    if not result:
        return json.dumps({"error": "Run not found"})
    return json.dumps({"run_id": run_id,
                        "suggestion": "Run retrieved. Use run_score and run_timeline for analysis."},
                       default=str)


def _blackbox_ingest(events: list[dict]) -> str:
    import json
    from eling.blackbox.store import TraceEvent
    count = 0
    for e in events:
        _get_blackbox().ingest(TraceEvent(**e))
        count += 1
    return json.dumps({"ingested": count})


# ── markdownify_* tools ──────────────────────────────────────────────

def _markdownify_file(filepath: str) -> str:
    md = _get_markitdown()
    if md is None:
        return '{"error": "markitdown not installed - run: pip install markitdown[all]"}'
    try:
        result = md.convert(filepath)
        return result.text_content
    except Exception as e:
        return f'{{"error": "{e}"}}'


def _markdownify_webpage(url: str) -> str:
    md = _get_markitdown()
    if md is None:
        return '{"error": "markitdown not installed - run: pip install markitdown[all]"}'
    try:
        result = md.convert_url(url)
        return result.text_content
    except Exception as e:
        return f'{{"error": "{e}"}}'


# ── Tool registry ─────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {}

def _r(name: str, fn, desc: str, props: dict | None = None,
       required: list[str] | None = None) -> None:
    n, d = _tool(name, fn, desc, props, required)
    TOOLS[n] = d


def _re(name: str, fn, desc: str) -> None:
    n, d = _empty_tool(name, fn, desc)
    TOOLS[n] = d


# brain
_r("brain_remember", _brain_remember,
   "Store content in memory (auto-routes to facts/kb)",
   {"content": {"type": "string", "description": "Content to store"},
    "layer": {"type": "string", "enum": ["auto", "facts", "kb"],
              "description": "Target layer"},
    "category": {"type": "string", "description": "Category tag"},
    "tags": {"type": "string", "description": "Comma-separated tags"},
    "title": {"type": "string", "description": "Title for KB entries"},
    "skip_dedup": {"type": "boolean", "description": "Skip dedup check"}},
   ["content"])

_r("brain_recall", _brain_recall,
   "Cross-layer search across all memory layers",
   {"query": {"type": "string", "description": "Search query"},
    "layers": {"type": "array", "items": {"type": "string"},
               "description": "Layers to search"},
    "limit": {"type": "integer", "description": "Max results"},
    "source": {"type": "string", "description": "Filter by agent source"}},
   ["query"])

_r("brain_probe", _brain_probe,
   "Get all facts about a single entity",
   {"entity": {"type": "string", "description": "Entity name"},
    "limit": {"type": "integer", "description": "Max results"}},
   ["entity"])

_r("brain_reason", _brain_reason,
   "Find facts connecting multiple entities via HRR",
   {"entities": {"type": "array", "items": {"type": "string"},
                 "description": "Entities to connect"},
    "limit": {"type": "integer", "description": "Max results"}},
   ["entities"])

_r("brain_think", _brain_think,
   "Synthesis + gap-analysis across memory",
   {"query": {"type": "string", "description": "Search query"},
    "entities": {"type": "array", "items": {"type": "string"},
                 "description": "Entities to reason across"},
    "limit": {"type": "integer", "description": "Max results"}},
   ["query"])

_re("brain_stats", _brain_stats, "Show brain statistics")

_r("brain_export", _brain_export,
   "Export memory layers as JSON or Markdown",
   {"format": {"type": "string", "enum": ["json", "markdown"]},
    "path": {"type": "string", "description": "Output file path"}})

_re("brain_link_stats", _brain_link_stats,
    "Zettelkasten link graph statistics")

_r("brain_linked_facts", _brain_linked_facts,
   "Get facts linked to a fact_id",
   {"fact_id": {"type": "integer", "description": "Fact ID"},
    "limit": {"type": "integer", "description": "Max links"}},
   ["fact_id"])

_r("brain_evolve", _brain_evolve,
   "Merge near-duplicate facts",
   {"threshold": {"type": "number",
                  "description": "Jaccard similarity threshold"}})

_r("brain_snapshot", _brain_snapshot,
   "Create a named snapshot of facts database",
   {"reason": {"type": "string",
               "description": "Why the snapshot is taken"}})

_re("brain_list_snapshots", _brain_list_snapshots,
    "List all available snapshots")

_r("brain_rollback", _brain_rollback,
   "Restore facts database from a snapshot",
   {"snapshot_id": {"type": "string",
                    "description": "Snapshot ID to restore"}},
   ["snapshot_id"])

_r("brain_search_temporal", _brain_search_temporal,
   "Cross-layer search with temporal filtering",
   {"query": {"type": "string", "description": "Search query"},
    "time_start": {"type": "string", "description": "ISO start date"},
    "time_end": {"type": "string", "description": "ISO end date"},
    "category": {"type": "string", "description": "Category filter"},
    "source": {"type": "string", "description": "Source filter"},
    "limit": {"type": "integer", "description": "Max results"}},
   ["query"])

_r("brain_verify", _brain_verify,
   "Check or record verification-on-stop status",
   {"status": {"type": "string",
               "enum": ["passed", "failed", "skipped", ""]},
    "command": {"type": "string"},
    "output": {"type": "string"},
    "spec_check": {"type": "boolean"},
    "changed_files": {"type": "array", "items": {"type": "string"}}})

_r("brain_verify_spec", _brain_verify_spec,
   "Run spec-kit conformance verification",
   {"changed_files": {"type": "array", "items": {"type": "string"}}})

# obsidian
_r("brain_obsidian_search", _brain_obsidian_search,
   "Search Obsidian vault files by content",
   {"query": {"type": "string", "description": "Search query"},
    "limit": {"type": "integer", "description": "Max results"}},
   ["query"])

_r("brain_obsidian_read", _brain_obsidian_read,
   "Read a Markdown file from the Obsidian vault",
   {"path": {"type": "string",
             "description": "Relative path under vault root"}},
   ["path"])

_r("brain_obsidian_write", _brain_obsidian_write,
   "Create or overwrite a file in the Obsidian vault",
   {"path": {"type": "string",
             "description": "Relative path under vault root"},
    "content": {"type": "string", "description": "Markdown body"},
    "title": {"type": "string", "description": "Frontmatter title"}},
   ["path", "content"])

_r("brain_obsidian_daily", _brain_obsidian_daily,
   "Create or append to today's daily note",
   {"content": {"type": "string",
                "description": "Markdown content to append"}})

_r("brain_obsidian_list", _brain_obsidian_list,
   "List Markdown files in the vault",
   {"folder": {"type": "string",
               "description": "Subfolder to scope to"}})

# continuum
_r("continuum_project_create", _continuum_project_create,
   "Register a project root in Continuum",
   {"path": {"type": "string", "description": "Canonical project root"},
    "name": {"type": "string", "description": "Human name"}},
   ["path"])

_r("continuum_project_get", _continuum_project_get,
   "Get a registered project by path",
   {"path": {"type": "string"}},
   ["path"])

_re("continuum_project_list", _continuum_project_list,
    "List all registered projects")

_r("continuum_knowledge_create", _continuum_knowledge_create,
   "Store a knowledge entry in Continuum",
   {"project": {"type": "string"}, "slug": {"type": "string"},
    "content": {"type": "string"},
    "kind": {"type": "string", "enum": ["fundamental", "situational"]},
    "title": {"type": "string"}},
   ["project", "slug", "content"])

_r("continuum_knowledge_get", _continuum_knowledge_get,
   "Fetch a knowledge entry body",
   {"project": {"type": "string"}, "slug": {"type": "string"}},
   ["project", "slug"])

_r("continuum_knowledge_list", _continuum_knowledge_list,
   "List knowledge entry metadata",
   {"project": {"type": "string"},
    "kind": {"type": "string",
             "enum": ["fundamental", "situational", ""]}},
   ["project"])

_r("continuum_knowledge_search", _continuum_knowledge_search,
   "Search knowledge entries",
   {"project": {"type": "string"}, "q": {"type": "string"},
    "limit": {"type": "integer"}},
   ["project", "q"])

_r("continuum_agent_register", _continuum_agent_register,
   "Register a dispatch agent (state=draft)",
   {"project": {"type": "string"}, "slug": {"type": "string"},
    "branch": {"type": "string"}, "worktree": {"type": "string"},
    "prompt": {"type": "string"},
    "reserved_paths": {"type": "array", "items": {"type": "string"}}},
   ["project", "slug"])

_r("continuum_agent_update", _continuum_agent_update,
   "Update an agent's status or fields",
   {"project": {"type": "string"}, "slug": {"type": "string"},
    "status": {"type": "string",
              "enum": ["draft", "active", "merged", "abandoned"]},
    "branch": {"type": "string"}, "worktree": {"type": "string"},
    "prompt": {"type": "string"},
    "merged_commit": {"type": "string"},
    "reserved_paths": {"type": "array", "items": {"type": "string"}}},
   ["project", "slug"])

_r("continuum_agent_get", _continuum_agent_get,
   "Get a single agent's registry record",
   {"project": {"type": "string"}, "slug": {"type": "string"}},
   ["project", "slug"])

_r("continuum_registry_list", _continuum_registry_list,
   "List dispatch agents for a project",
   {"project": {"type": "string"},
    "status": {"type": "string",
              "enum": ["", "draft", "active", "merged", "abandoned"]},
    "limit": {"type": "integer"}, "offset": {"type": "integer"}},
   ["project"])

_r("continuum_plot_get", _continuum_plot_get,
   "Get the canonical PLOT.md for a project",
   {"project": {"type": "string"}},
   ["project"])

_r("continuum_plot_update", _continuum_plot_update,
   "Mutate PLOT.md via a unified diff",
   {"project": {"type": "string"},
    "diff": {"type": "string", "description": "Unified-diff text"}},
   ["project", "diff"])

_r("continuum_reservations", _continuum_reservations,
   "Show reserved_path collisions across active agents",
   {"project": {"type": "string"}},
   ["project"])

# blackbox
_re("blackbox_stats", _blackbox_stats, "Get blackbox store statistics")

_r("blackbox_runs_list", _blackbox_runs_list,
   "List recorded blackbox runs",
   {"host": {"type": "string"}, "project_key": {"type": "string"},
    "limit": {"type": "integer"}})

_r("blackbox_run_get", _blackbox_run_get,
   "Get full details for a run",
   {"run_id": {"type": "string"},
    "include_events": {"type": "boolean"}},
   ["run_id"])

_r("blackbox_run_score", _blackbox_run_score,
   "Score a run's 11-metric context efficiency",
   {"run_id": {"type": "string"},
    "archetype": {"type": "string",
                 "enum": ["auto", "research", "debug", "ops", "feature", "edit"]}},
   ["run_id"])

_r("blackbox_run_effectiveness", _blackbox_run_effectiveness,
   "Score a run's outcome effectiveness",
   {"run_id": {"type": "string"}},
   ["run_id"])

_r("blackbox_run_timeline", _blackbox_run_timeline,
   "Get the causal timeline for a run",
   {"run_id": {"type": "string"}},
   ["run_id"])

_r("blackbox_run_suggest", _blackbox_run_suggest,
   "Get optimization suggestions for a run",
   {"run_id": {"type": "string"}},
   ["run_id"])

_r("blackbox_ingest", _blackbox_ingest,
   "Ingest raw telemetry events",
   {"events": {"type": "array", "items": {"type": "object"}}},
   ["events"])

# markdownify
_r("markdownify_file", _markdownify_file,
   "Convert any supported file to Markdown (PDF, DOCX, XLSX, PPTX, image, audio)",
   {"filepath": {"type": "string", "description": "Path to the file"}},
   ["filepath"])

_r("markdownify_webpage", _markdownify_webpage,
   "Convert a web URL to Markdown",
   {"url": {"type": "string", "description": "Web URL to convert"}},
   ["url"])
