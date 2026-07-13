# Plugins

Eling Agent supports a simple plugin system.

## Creating a Plugin

Drop a `.py` file in `plugins/` with a `TOOLS` dict:

```python
TOOLS = [
    {
        "name": "my_tool",
        "description": "My custom tool",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string"}
            },
            "required": ["arg1"]
        }
    }
]

def my_tool(args: dict) -> str:
    """Implement the tool logic."""
    return f"Hello, {args['arg1']}!"
```

## Built-in Plugins

- **shell** — Run shell commands, list directories
- **files** — (planned) file read/write operations
