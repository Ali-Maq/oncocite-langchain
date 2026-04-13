# OncoCITE skills integration

Supplementary Note S5 of the manuscript describes a "skills file
encapsulating OncoCITE capabilities… for direct integration with
Claude-based workflows." That file is [`oncocite.skill.json`](oncocite.skill.json)
in this directory.

It declares:

- **Metadata** — name, version, license (MIT), and a pointer to the paper
- **MCP server** — how to launch the stdio MCP server (`python -m mcp_server`)
- **Tool registry** — the 22 tools from Supplementary Table S15, with
  their owning agent and purpose, so an LLM agent can pick the right tool
  for a given step
- **Usage examples** — invoking the full pipeline (`run_extraction.py`)
  and invoking individual tools over MCP

To attach the skill to a Claude Desktop or MCP-compatible client, point
the client at the server command in the skill file:

```json
{
  "mcpServers": {
    "oncocite": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/oncocite-langchain"
    }
  }
}
```

The agent will then be able to call any of the 22 tools (Reader /
Planner / Extractor / Critic / Normalizer / Orchestrator) directly.
