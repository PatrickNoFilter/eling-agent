"""
Shell plugin for Eling — provides run_shell and run_parallel tools.
"""

import concurrent.futures
import os
import subprocess


def run_shell(command: str) -> str:
    """Run a single shell command with a 60-second timeout."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout
        if result.stderr:
            if output:
                output += "\n--- stderr ---\n" + result.stderr
            else:
                output = result.stderr
        if result.returncode != 0:
            output = f"(exit code {result.returncode})\n{output}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out after 60s)"
    except Exception as exc:
        return f"(error: {exc})"


def _exec_shell(cmd: str) -> str:
    """Internal worker that runs one command and captures output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = result.stdout
        if result.stderr:
            if out:
                out += "\n--- stderr ---\n" + result.stderr
            else:
                out = result.stderr
        if result.returncode != 0:
            out = f"(exit code {result.returncode})\n{out}"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out after 60s)"
    except Exception as exc:
        return f"(error: {exc})"


def run_parallel(commands: list[str]) -> str:
    """Run multiple shell commands concurrently using thread-level parallelism.
    Each command spawns its own subprocess (GIL-safe), so threads are efficient."""
    max_workers = os.cpu_count() or 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_exec_shell, cmd): cmd for cmd in commands}
        results = []
        for future in concurrent.futures.as_completed(futures):
            cmd = futures[future]
            try:
                output = future.result()
            except Exception as exc:
                output = f"(error: {exc})"
            results.append(f"$ {cmd}\n{output}")
    return "\n\n".join(results)


TOOLS = {
    "run_shell": {
        "function": run_shell,
        "description": "Run a single shell command with a 60-second timeout. Returns stdout (and stderr if any).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                }
            },
            "required": ["command"],
        },
    },
    "run_parallel": {
        "function": run_parallel,
        "description": "Run multiple independent shell commands concurrently using all CPU cores. Each command gets its own process. Results are joined.",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of shell commands to run in parallel",
                }
            },
            "required": ["commands"],
        },
    },
}
