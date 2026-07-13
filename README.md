<div align="center">

# 🧠 Eling Agent

**Personal auto-learning agent CLI — memory, skills, MCP tools, terminal UI**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/github-PatrickNoFilter/eling--agent-8A2BE2)](https://github.com/PatrickNoFilter/eling-agent)

*"Eling" (Javanese): to remember, to be conscious, to be aware*

</div>

---

## ✨ What is Eling Agent?

**Eling Agent** is a lightweight, personal auto-learning agent that runs in your terminal. It combines:

- **🧠 Local memory** — stores past exchanges, learns from experience
- **📚 Skill library** — auto-discovers reusable patterns from your conversations
- **📦 Workspace Manager** — copy-on-write file editing with automatic project root detection
- **⏱ Live elapsed timer** — real-time thinking spinner with elapsed time counter
- **🔧 MCP tools** — connect any MCP server (web search, filesystem, firecrawl, etc.)
- **🎨 Rich TUI** — beautiful terminal UI with banner, thinking spinner, session uptime
- **🧩 Plugin system** — extend with Python plugins (shell, files, web)
- **⏱ Session persistence** — tracks uptime, plan steps, tool timings

It uses the **OpenCode Zen API** for LLM inference — a free, fast API compatible with OpenAI's chat completions format.

---

## 🚀 Quick Start

### Install

```bash
# Clone the repo
git clone https://github.com/PatrickNoFilter/eling-agent.git
cd eling-agent

# Install deps
pip install -r requirements.txt

# Configure your Zen API key
cp config.example.json config.json
# Edit config.json with your key from https://opencode.ai/zen
```

### Run

```bash
# Interactive REPL mode
python3 agent.py

# One-shot mode
python3 agent.py "What files are in this directory?"

# Compact mode (no banner, minimal output)
python3 agent.py --compact
```

### Setup

Get a free API key at [opencode.ai/zen](https://opencode.ai/zen) and set it in `config.json`:

```json
{
  "zen_api_key": "sk-zen-your-key-here",
  "zen_model": "deepseek-v4-flash-free"
}
```

---

## 🎮 Commands

| Command | Description |
|---------|-------------|
| `python3 agent.py` | Launch interactive REPL with TUI |
| `python3 agent.py "query"` | One-shot mode |
| `python3 agent.py --compact` | Compact mode (minimal output) |
| `exit` / `quit` | Exit the REPL |

---

## 🔌 MCP Servers

Eling Agent supports any MCP server. Configure them in `config.json`:

```json
{
  "mcp_servers": {
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

MCP tools are automatically loaded and presented to the model. Use `mcp__` prefixed tool names in responses.

---

## 🧩 Plugins

Built-in plugins:

- **shell** — run shell commands, list directories
- **files** — (planned) file read/write operations

Drop a `.py` file with a `TOOLS` dict into `plugins/` to add your own.

---

## 🧠 Memory & Skills

Eling Agent learns from every exchange:

- **Memory** — past Q&A pairs are stored and retrieved by relevance (BM25 + cosine similarity)
- **Skills** — after each response, the model decides if a reusable skill should be saved
- **Persistence** — database files in `agent_memory.db` and `agent_skills.db`

---

## 📦 Project Structure

```
eling-agent/
├── agent.py              # Main entry point — REPL loop, tool orchestration
├── tui.py                # Terminal UI — banner, spinner, plan panel, markdown
├── provider.py           # ZenProvider — OpenAI-compatible API client
├── mcp_client.py         # MCP client — stdio-based server manager
├── memory.py             # MemoryStore — BM25 + cosine similarity retrieval
├── skills.py             # SkillLibrary — auto-learned skill storage
├── textsim.py            # Text utilities — tokenizer, similarity
├── plugins/
│   ├── __init__.py       # Plugin loader
│   └── shell_plugin.py   # Shell command execution
├── config.example.json   # Template configuration
├── requirements.txt      # Python dependencies
├── pyproject.toml        # Package metadata
└── LICENSE               # MIT license
```

---

## ⚙️ Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `zen_api_key` | — | Your OpenCode Zen API key |
| `zen_base_url` | `https://opencode.ai/zen/v1` | API endpoint |
| `zen_model` | `deepseek-v4-flash-free` | Model to use |
| `max_tool_rounds` | `6` | Max tool call iterations per turn |
| `memory_db` | `agent_memory.db` | Memory database path |
| `skills_db` | `agent_skills.db` | Skills database path |
| `mcp_servers` | `{}` | MCP server configurations |

---

## 🤝 Credits

Eling Agent was created by **PatrickNoFilter**.

- Built on the **Hermes Agent** framework patterns
- Uses **Rich** for terminal rendering
- Uses **OpenCode Zen** API for LLM inference
- Inspired by Zero/OpenCode CLI agent patterns
- The name *Eling* comes from Javanese *eling* — to remember, to be conscious

---

## 📄 License

MIT © 2026 PatrickNoFilter
