# MCP Integration

Eling Agent supports the Model Context Protocol (MCP) for connecting to external tools.

## Configuration

Add MCP servers to `config.json`:

```json
{
  "mcp_servers": {
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"]
    }
  }
}
```

## Supported Servers

- **Firecrawl** — Web scraping and search
- **Filesystem** — Local file access
- **Any stdio-based MCP server** — Just configure the command and args
