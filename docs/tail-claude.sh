tail -F ~/.claude/projects/*/*.jsonl | grep -v "^[^{]" | jq -rc 2>/dev/null | tee claude.jsonl
tail -F ~/.claude/projects/*/*.jsonl 2>/dev/null | stdbuf -oL grep "^{" | jq -rc .
