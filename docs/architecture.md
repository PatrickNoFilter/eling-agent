# Architecture

Eling Agent follows a modular, event-driven architecture:

```
┌─────────────────────────────────────────────┐
│                  agent.py                    │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ provider  │ │ tui      │ │ mcp_client  │  │
│  │ (LLM API) │ │ (UI)     │ │ (MCP)       │  │
│  └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ memory   │ │ skills   │ │ workspace   │  │
│  │ (store)  │ │ (lib)    │ │ (manager)   │  │
│  └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────┐ ┌──────────┐                  │
│  │ plugins  │ │ textsim  │                  │
│  └──────────┘ └──────────┘                  │
└─────────────────────────────────────────────┘
```

## Core Loop

1. **Input** — User provides a message or command
2. **Context** — Memory + skills are retrieved and added to context
3. **Inference** — LLM generates a response (with optional tool calls)
4. **Tools** — Tool calls are dispatched via MCP or plugins
5. **Learning** — New memories and skills are extracted
6. **Output** — Response is displayed via TUI
