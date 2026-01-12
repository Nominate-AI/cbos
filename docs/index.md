# CBOS Documentation

CBOS (Claude Code Operating System) is a session manager for running multiple Claude Code instances with real-time streaming, WebSocket API, and terminal UI.

## Quick Start

See the main [README.md](../README.md) for installation and usage instructions.

```bash
# Check API status (running as systemd service)
sudo systemctl status cbos

# Launch the TUI
cbos
```

## Documentation Structure

| Document | Description |
|----------|-------------|
| [QUICK-START.md](QUICK-START.md) | Getting started guide |
| [ORCHESTRATOR-USAGE.md](ORCHESTRATOR-USAGE.md) | Pattern orchestrator CLI usage |
| [CONVERSATION-FEATURES.md](CONVERSATION-FEATURES.md) | Conversation feature documentation |
| [orchestrator/](orchestrator/) | Orchestrator implementation details |

## Archived Documentation

Historical planning and strategy documents are in [archive/](archive/).
