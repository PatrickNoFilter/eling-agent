"""
Workspace Manager — copy-on-write workspace for safe file editing.

Instead of editing files in-place, the manager:
1. Detects project roots from tool call arguments
2. Copies the project to /root/eling-workspce/auto-<ts>/<name>/
3. Rewrites file paths in tool arguments to point to the workspace copy
4. After tools complete, rewrites paths back in results
5. Syncs changed workspace files back to originals
"""

import json
import logging
import os
import shutil
from datetime import datetime

log = logging.getLogger("workspace")

# Tools whose string arguments contain filesystem paths that can be remapped
TOOLS_THAT_USE_FS_PATHS = {
    "run_shell", "run_parallel",
    "markdownify_file",
    "brain_verify", "brain_verify_spec",
}

# Project root markers (files that indicate a project root directory)
PROJECT_MARKERS = [
    ".git", "setup.py", "pyproject.toml", "setup.cfg",
    "package.json", "Cargo.toml", "go.mod", "Gemfile",
    "Makefile", "Rakefile", "CMakeLists.txt",
    "pom.xml", "build.gradle", "SConstruct",
]


class WorkspaceManager:
    """Manages a workspace copy of project files for safe editing."""

    def __init__(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.workspace_root = f"/root/eling-workspce/auto-{ts}"
        os.makedirs(self.workspace_root, exist_ok=True)
        # Maps original_dir_abspath -> workspace_dir_abspath
        self.dir_map: dict[str, str] = {}
        self.active = False
        self._project_roots: set[str] = set()

    # ── Project root detection ────────────────────────────────────────

    @staticmethod
    def _find_project_root(file_path: str) -> str | None:
        """Walk up from file_path to find a project root directory."""
        path = os.path.abspath(file_path)
        # If it's a file, start from its parent
        if os.path.isfile(path):
            path = os.path.dirname(path)
        while True:
            parent = os.path.dirname(path)
            if parent == path:  # reached root /
                return None
            for marker in PROJECT_MARKERS:
                if os.path.exists(os.path.join(path, marker)):
                    return path
            # Also treat any dir containing Python files as a project root
            # as a fallback if we haven't found markers yet
            path = parent

    # ── Setup from tool calls ─────────────────────────────────────────

    def setup_from_tool_calls(self, tool_calls: list[dict]) -> bool:
        """Scan tool calls for file paths, copy projects to workspace.

        Returns True if any projects were copied to workspace.
        """
        if not tool_calls:
            return False

        # Collect all filesystem paths mentioned in tool call arguments
        paths: set[str] = set()
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "")
            if func_name not in TOOLS_THAT_USE_FS_PATHS:
                continue

            args_raw = tc.get("function", {}).get("arguments", "{}")
            if isinstance(args_raw, str):
                try:
                    arguments = json.loads(args_raw)
                except json.JSONDecodeError:
                    continue
            else:
                arguments = args_raw

            self._extract_paths_from_value(arguments, paths)

        if not paths:
            return False

        # Find project roots for each path
        roots: set[str] = set()
        for p in paths:
            root = self._find_project_root(p)
            if root:
                roots.add(root)

        if not roots:
            # Fallback: for any file path, use its closest existing ancestor
            for p in paths:
                dir_path = p if os.path.isdir(p) else os.path.dirname(p)
                while dir_path and dir_path != "/":
                    if os.path.isdir(dir_path):
                        roots.add(dir_path)
                        break
                    dir_path = os.path.dirname(dir_path)

        if not roots:
            return False

        # Copy each project root to workspace
        for root in sorted(roots, key=len):
            # Skip if already mapped
            if root in self.dir_map:
                continue
            # Skip agent's own runtime directory (don't copy running code)
            project_name = os.path.basename(root.rstrip("/"))
            if not project_name:
                continue

            ws_dir = os.path.join(self.workspace_root, project_name)

            # Remove stale workspace copy if exists
            if os.path.exists(ws_dir):
                shutil.rmtree(ws_dir)

            # Copy project to workspace
            try:
                shutil.copytree(
                    root, ws_dir, symlinks=True,
                    ignore_dangling_symlinks=True,
                    ignore=shutil.ignore_patterns('.git'),
                )
                self.dir_map[root] = ws_dir
                self._project_roots.add(root)
                log.info("Copied %s -> %s (%d files)", root, ws_dir,
                         sum(len(files) for _, _, files in os.walk(ws_dir)))
            except RecursionError:
                log.warning("Skipped %s: circular symlink detected", root)
            except Exception as exc:
                log.warning("Failed to copy %s to workspace: %s", root, exc)

        self.active = bool(self.dir_map)
        return self.active

    @classmethod
    def _extract_paths_from_value(cls, value, paths: set[str]) -> None:
        """Recursively extract filesystem paths from a JSON-like value."""
        if isinstance(value, str):
            # Split on whitespace to handle shell command syntax
            for token in value.split():
                token = token.strip("\"'()[]{};,|&<>!")
                # Basic path check: contains / and exists or looks like a path
                if "/" in token and not token.startswith("--"):
                    # Check absolute paths and relative paths that exist
                    if token.startswith("/") and os.path.exists(token):
                        paths.add(os.path.abspath(token))
                    elif os.path.exists(token):
                        paths.add(os.path.abspath(token))
        elif isinstance(value, list):
            for item in value:
                cls._extract_paths_from_value(item, paths)
        elif isinstance(value, dict):
            for v in value.values():
                cls._extract_paths_from_value(v, paths)

    # ── Path remapping ────────────────────────────────────────────────

    def remap_str(self, text: str) -> str:
        """Replace original paths with workspace paths in a string."""
        if not self.active or not text:
            return text
        result = text
        # Replace longest paths first to avoid partial replacements
        for orig, ws in sorted(self.dir_map.items(), key=lambda x: -len(x[0])):
            result = result.replace(orig, ws)
        return result

    def unmap_str(self, text: str) -> str:
        """Replace workspace paths back with original paths in a string."""
        if not self.active or not text:
            return text
        result = text
        for orig, ws in sorted(self.dir_map.items(), key=lambda x: -len(x[1])):
            result = result.replace(ws, orig)
        return result

    def remap_args(self, func_name: str, arguments: dict) -> dict:
        """Remap file paths in tool arguments to workspace paths.

        Only remaps for tools known to use filesystem paths.
        """
        if not self.active or func_name not in TOOLS_THAT_USE_FS_PATHS:
            return arguments
        return self._remap_value(arguments)

    def _remap_value(self, v):
        if isinstance(v, str):
            return self.remap_str(v)
        elif isinstance(v, list):
            return [self._remap_value(item) for item in v]
        elif isinstance(v, dict):
            return {k: self._remap_value(val) for k, val in v.items()}
        return v

    def remap_result(self, func_name: str, content: str) -> str:
        """Remap workspace paths back to original paths in tool results."""
        if not self.active or func_name not in TOOLS_THAT_USE_FS_PATHS:
            return content
        return self.unmap_str(content)

    # ── Sync back ─────────────────────────────────────────────────────

    def sync_back(self) -> int:
        """Copy changed files from workspace back to original locations.

        Returns the number of files that were updated.
        """
        if not self.active:
            return 0

        count = 0
        for orig_dir, ws_dir in self.dir_map.items():
            if not os.path.isdir(ws_dir):
                continue

            for dirpath, _dirnames, filenames in os.walk(ws_dir):
                rel = os.path.relpath(dirpath, ws_dir)
                target_dir = os.path.join(orig_dir, rel)

                for fn in filenames:
                    ws_file = os.path.join(dirpath, fn)
                    orig_file = os.path.join(target_dir, fn)

                    # Skip if neither file exists (shouldn't happen)
                    if not os.path.isfile(ws_file):
                        continue

                    # Compare content; skip if unchanged
                    if os.path.isfile(orig_file):
                        try:
                            with open(ws_file, "rb") as f:
                                ws_content = f.read()
                            with open(orig_file, "rb") as f:
                                orig_content = f.read()
                            if ws_content == orig_content:
                                continue
                        except OSError:
                            pass  # Fall through to copy

                    # Copy workspace file back to original location
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        shutil.copy2(ws_file, orig_file)
                        count += 1
                    except OSError as exc:
                        # Warning kept but note: occurs inside TUI status context
                        log.warning("Failed to sync back: %s", exc)

        self.active = False
        # Log removed: TUI displays this message in agent.py after sync_back()
        return count

    def get_workspace_path(self, original_path: str) -> str | None:
        """Get the workspace path for an original path, if mapped."""
        if not self.active:
            return None
        ap = os.path.abspath(original_path)
        # Check exact file match
        for orig, ws in self.dir_map.items():
            if ap.startswith(orig):
                return ap.replace(orig, ws, 1)
        return None

    def summary(self) -> str:
        """Return a human-readable summary of the workspace mapping."""
        if not self.active:
            return "Workspace: inactive"
        parts = [f"Workspace root: {self.workspace_root}"]
        for orig, ws in self.dir_map.items():
            parts.append(f"  {orig}  →  {ws}")
        return "\n".join(parts)
