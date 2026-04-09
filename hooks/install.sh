#!/usr/bin/env bash
# Install TermPipe git hooks into .git/hooks/
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_SRC="$REPO_ROOT/hooks"
HOOKS_DEST="$REPO_ROOT/.git/hooks"

for hook in post-commit commit-msg; do
    cp "$HOOKS_SRC/$hook" "$HOOKS_DEST/$hook"
    chmod +x "$HOOKS_DEST/$hook"
    echo "✅ installed $hook"
done
echo "Done. Hooks active for $REPO_ROOT"
