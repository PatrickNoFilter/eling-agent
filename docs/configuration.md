# Configuration

See [config.example.json](../config.example.json) for the template.

## Key Options

| Key | Default | Description |
|-----|---------|-------------|
| `zen_api_key` | — | Your OpenCode Zen API key |
| `zen_base_url` | `https://opencode.ai/zen/v1` | API endpoint |
| `zen_model` | `deepseek-v4-flash-free` | Model to use |
| `max_tool_rounds` | `6` | Max tool call iterations per turn |
| `memory_db` | `agent_memory.db` | Memory database path |
| `skills_db` | `agent_skills.db` | Skills database path |
| `mcp_servers` | `{}` | MCP server configurations |
| `theme` | `"cobalt"` | TUI color theme (blue, pink, green, yellow, red, white, ocean, twilight, pastel, cobalt) |
