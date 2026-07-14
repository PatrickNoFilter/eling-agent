<div align="center">

# 🧠 Eling Agent

**Personal auto-learning agent CLI — memory, skills, MCP tools, workspace, and terminal UI**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/github-PatrickNoFilter/eling--agent-8A2BE2)](https://github.com/PatrickNoFilter/eling-agent)
[![Version](https://img.shields.io/badge/version-0.2.0-blueviolet)](https://github.com/PatrickNoFilter/eling-agent/releases)

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
- **🎨 Rich TUI** — beautiful terminal UI with banner, thinking spinner, session uptime, 10 color themes
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

Or run the interactive setup wizard:

```bash
python3 agent.py --setup
```

This lets you configure the provider, API key, model, agent mode, and **color theme** (10 palettes to choose from).

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
| `python3 agent.py --setup` | Interactive setup wizard (provider, theme) |
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
├── tui.py                # Terminal UI — banner, spinner, plan panel, markdown, themes
├── provider.py           # ZenProvider — OpenAI-compatible API client
├── mcp_client.py         # MCP client — stdio-based server manager (env support)
├── memory.py             # MemoryStore — BM25 + cosine similarity retrieval, dedup
├── skills.py             # SkillLibrary — auto-learned skill storage
├── textsim.py            # Text utilities — tokenizer, similarity
├── workspace_manager.py  # Copy-on-write file editing with project detection
├── src/eling/cli.py      # Interactive setup wizard (provider, theme)
├── plugins/
│   ├── __init__.py       # Plugin loader
│   └── shell_plugin.py   # Shell command execution
├── config.example.json   # Template configuration
├── requirements.txt      # Python dependencies
├── pyproject.toml        # Package metadata (elin 0.2.0)
├── CREDITS.md            # Credits and acknowledgements
├── CREDITS.library.md    # Library-level credits
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
| `theme` | `"cobalt"` | Color theme for TUI (blue, pink, green, yellow, red, white, ocean, twilight, pastel, cobalt) |

---

## 📚 Dependencies

### Core

| Package | Version | Purpose |
|---------|---------|---------|
| [eling](https://pypi.org/project/eling/) | ≥0.12.0 | 8-layer second-brain memory library (HRR, BM25, Zettelkasten) |
| [httpx](https://pypi.org/project/httpx/) | ≥0.27 | HTTP client for API calls and Notion layer |
| [requests](https://pypi.org/project/requests/) | ≥2.31 | HTTP client for legacy API calls |
| [prompt_toolkit](https://pypi.org/project/prompt-toolkit/) | ≥3.0 | Interactive REPL prompt |
| [rich](https://pypi.org/project/rich/) | ≥13.0 | Terminal UI rendering (markdown, panels, tables) |

### Optional

| Group | Packages | Purpose |
|-------|----------|---------|
| `notion` | httpx | Notion integration layer |
| `hrr` | numpy≥1.24 | Holographic Reduced Representations |
| `embeddings` | sentence-transformers≥3.0 | Embedding-based retrieval |
| `markdownify` | markitdown[pdf] | Document-to-Markdown conversion |
| `markdownify_all` | markitdown[all] | All document formats |
| `all` | everything above | Full feature set |

Install extras with:

```bash
pip install "eling-agent[hrr,embeddings,notion,markdownify]"
```

---

## 🤝 Credits

Eling Agent was created by **PatrickNoFilter** ([@PatrickNoFilter](https://github.com/PatrickNoFilter)).

### Built With

| Project | Contribution |
|---------|-------------|
| **OpenCode Zen** | Free LLM inference API |
| **Zero / OpenCode CLI** | CLI agent patterns, telemetry format |
| **Rich** | Terminal rendering engine |
| **Eling memory library** | 8-layer second brain (HRR, BM25, Zettelkasten) |
| **Agent-Blackbox** (Nous Research) | Flight recorder, 11-metric context scoring |
| **Continuum** | Multi-agent orchestration, PLOT protocol |
| **Firecrawl MCP** | Web scraping and search |
| **Markdownify MCP** (Zach Caceres) | Document conversion |
| **Claude Code / Codex** | Tool-calling loop patterns |
| **dusterbloom** | HRR phase-encoding implementation |

See [CREDITS.md](CREDITS.md) and [CREDITS.library.md](CREDITS.library.md) for full attribution.

---

## 📄 License

MIT © 2026 PatrickNoFilter
