#!/bin/bash
# PreToolUse hook: stops Claude from running git commands that discard work or rewrite
# shared history. The only push allowed is `git push [-u] origin <feature-branch>`;
# pushing main, force-pushing and deleting remote refs are left to the maintainer.

command=$(jq -r '.tool_input.command // ""')

block() {
  echo "BLOCKED by .claude/hooks/block-dangerous-git.sh: $1. Ask the maintainer to run it." >&2
  exit 2
}

if grep -qE 'git\b.*\b(reset --hard|clean -[a-zA-Z]*f|branch -D|checkout \.|restore \.)' <<<"$command"; then
  block "destructive git command"
fi

if grep -qE 'git\b.*\bpush\b' <<<"$command"; then
  branch=$(grep -oE '[^ ]+$' <<<"$command")
  if ! grep -qE '^git push (-u |--set-upstream )?origin [A-Za-z0-9._/-]+$' <<<"$command" ||
    [[ $branch =~ ^(main|master)$ ]]; then
    block "only 'git push [-u] origin <feature-branch>' is allowed"
  fi
fi

exit 0
