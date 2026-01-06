tail -F ~/.claude/projects/*/*.jsonl | grep -v "^[^{]" | jq -rc 2>/dev/null | tee claude.jsonl
