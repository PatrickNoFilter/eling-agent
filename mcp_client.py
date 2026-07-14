"""
Minimal MCP (Model Context Protocol) client over stdio JSON-RPC 2.0.
No SDK dependency — pure Python with subprocess + threading.
"""

import json
import logging
import subprocess
import threading
from queue import Queue, Empty
from typing import Any

log = logging.getLogger("mcp_client")


class MCPServerConnection:
    """Manages a single MCP server subprocess with JSON-RPC 2.0 over stdio."""

    def __init__(self, name: str, command: list[str], env: dict = None):
        self.name = name
        self.command = command
        self.env = env or None
        self._proc: subprocess.Popen | None = None
        self._recv_thread: threading.Thread | None = None
        self._responses: dict[int, Any] = {}
        self._response_queue: Queue = Queue()
        self._lock = threading.Lock()
        self._req_id = 0
        self._closed = False
        self.tools: list[dict] = []
        self._read_thread: threading.Thread | None = None

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def start(self):
        """Spawn the subprocess, perform handshake, and fetch tools."""
        log.info("Starting MCP server: %s (%s)", self.name, " ".join(self.command))
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )
        # Start a reader thread that collects stdout lines
        self._read_thread = threading.Thread(target=self._reader, daemon=True)
        self._read_thread.start()

        # Start a stderr reader thread that logs server-side errors
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._stderr_thread.start()

        # Initialize handshake
        init_resp = self._send_request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "eling", "version": "0.1.0"},
            },
        )
        if init_resp and "error" in init_resp:
            raise RuntimeError(
                f"MCP server '{self.name}' initialize error: {init_resp['error']}"
            )

        # Notify initialized
        self._send_notification("notifications/initialized", {})

        # List tools
        tools_resp = self._send_request("tools/list", {})
        if tools_resp and "error" in tools_resp:
            log.warning(
                "MCP server '%s' tools/list error: %s", self.name, tools_resp["error"]
            )
        else:
            self.tools = tools_resp.get("result", {}).get("tools", [])
            log.info("MCP server '%s' loaded %d tools", self.name, len(self.tools))

    def _reader(self):
        """Read stdout lines from the subprocess and route responses."""
        if not self._proc or not self._proc.stdout:
            return
        try:
            for line in self._proc.stdout:
                if self._closed:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("MCP non-JSON from '%s': %s", self.name, line[:200])
                    continue
                # Route response
                if "id" in msg:
                    self._response_queue.put(msg)
        except (ValueError, OSError):
            pass

    def _stderr_reader(self):
        """Read stderr lines from the subprocess and log them as warnings."""
        if not self._proc or not self._proc.stderr:
            return
        try:
            for line in self._proc.stderr:
                if self._closed:
                    break
                line = line.strip()
                if line:
                    log.warning("MCP '%s' stderr: %s", self.name, line[:500])
        except (ValueError, OSError):
            pass

    def _send_request(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        self._write_line(payload)

        # Wait for matching response (with timeout)
        timeout = 30
        deadline = threading.Timer(timeout, lambda: None)
        deadline.start()
        try:
            while True:
                try:
                    resp = self._response_queue.get(timeout=timeout)
                    if resp.get("id") == req_id:
                        return resp
                    # Mismatched id — could be a notification or prev timeout
                    # Put it back? For simplicity, just skip.
                except Empty:
                    log.warning(
                        "MCP server '%s' request %d timed out", self.name, req_id
                    )
                    return None
        finally:
            deadline.cancel()

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no id, no response)."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_line(payload)

    def _write_line(self, payload: dict):
        """Write a JSON line to the subprocess stdin."""
        if not self._proc or not self._proc.stdin:
            raise RuntimeError(f"MCP server '{self.name}' not running")
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool on this server and return the result."""
        resp = self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        if resp is None:
            return {"error": f"Tool call '{name}' timed out", "result": None}
        if "error" in resp:
            return {"error": resp["error"], "result": None}
        return resp.get("result", {})

    def stop(self):
        """Terminate the subprocess."""
        self._closed = True
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None

    def __del__(self):
        self.stop()


class MCPManager:
    """Manages multiple MCP server connections with lazy parallel init.

    Servers are *not* started at construction — they connect on first
    use (``openai_tools()`` or ``call()``).  This keeps agent startup
    instant regardless of how many MCP servers are configured.
    """

    # Well-known env vars whose empty value signals a misconfigured server
    _REQUIRED_ENV_KEYS = {
        "firecrawl": "FIRECRAWL_API_KEY",
        "github": "GITHUB_TOKEN",
        "e2b": "E2B_API_KEY",
        "ref_tools": "REF_API_KEY",
        "postgres": "DATABASE_URL",
    }

    def __init__(self, servers_config: dict[str, dict]):
        self._configs: dict[str, dict] = {}
        self.connections: dict[str, MCPServerConnection] = {}
        self._connected = False

        for name, cfg in servers_config.items():
            if name.startswith("_"):
                log.info("Skipping disabled MCP server: %s", name)
                continue
            env = cfg.get("env", {})
            # Skip servers whose required API key is empty
            required_key = self._REQUIRED_ENV_KEYS.get(name)
            if required_key and not env.get(required_key):
                log.info("Skipping MCP server '%s' — %s not set", name, required_key)
                continue
            self._configs[name] = cfg

    def _start_one(self, name: str, cfg: dict) -> MCPServerConnection | None:
        """Start a single MCP server and return its connection (or None)."""
        command = [cfg.get("command", "")]
        command.extend(cfg.get("args", []))
        conn = MCPServerConnection(name, command, env=cfg.get("env"))
        try:
            conn.start()
            return conn
        except Exception as exc:
            log.error("Failed to start MCP server '%s': %s", name, exc)
            return None

    def _ensure_connected(self):
        """Connect all configured servers in parallel (idempotent)."""
        if self._connected:
            return
        self._connected = True

        import concurrent.futures

        missing = [n for n in self._configs if n not in self.connections]
        if not missing:
            return

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(missing), 8)
        ) as pool:
            fut = {
                n: pool.submit(self._start_one, n, self._configs[n])
                for n in missing
            }
            for name, f in fut.items():
                conn = f.result()
                if conn is not None:
                    self.connections[name] = conn
                    log.info("MCP server '%s' started successfully", name)

    def openai_tools(self) -> list[dict]:
        """Return all server tools formatted as OpenAI tool schemas,
        "namespaced as mcp__<server>__<tool_name>.

        Triggers lazy connection of all servers on first call.
        """
        self._ensure_connected()
        tools = []
        for name, conn in self.connections.items():
            for tool in conn.tools:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"mcp__{name}__{tool['name']}",
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {}),
                        },
                    }
                )
        return tools

    def call(self, name: str, args: dict) -> dict:
        """
        Route a tool call to the right connection by parsing
        the mcp__<server>__<tool> namespace.  Triggers lazy
        connection on first use.
        """
        self._ensure_connected()
        parts = name.split("__", 2)
        if len(parts) < 3 or not parts[0] == "mcp":
            return {"error": f"Invalid MCP tool name: {name}"}
        server_name = parts[1]
        tool_name = parts[2]
        conn = self.connections.get(server_name)
        if not conn:
            return {"error": f"MCP server '{server_name}' not available"}
        return conn.call_tool(tool_name, args)

    def stop_all(self):
        """Stop every MCP connection."""
        for name, conn in self.connections.items():
            log.info("Stopping MCP server: %s", name)
            try:
                conn.stop()
            except Exception as exc:
                log.warning("Error stopping MCP server '%s': %s", name, exc)
        self.connections.clear()
