#!/bin/bash
# Claude Code Stop hook: after each Claude reply, commit changed code files and push them to origin.
# Only code/doc files are staged (allowlist below), so tracking_address.json, data exports, images,
# results/ and secrets are never committed. The commit is skipped if the staged diff looks like it
# contains an API key or a signed photo URL.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
branch=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0   # detached HEAD: do nothing

say() { jq -cn --arg m "$1" '{systemMessage: $m}'; }

# Code and docs only. Ignored files (.env, results/, valid_images/, delivery_data*.json, ...) are skipped by git.
git add -A -- '*.py' '*.js' '*.mjs' '*.html' '*.css' '*.md' '*.sh' \
  'chrome_extension/*.json' '.gitignore' 2>/dev/null

files=$(git diff --cached --name-only)
[ -z "$files" ] && exit 0

if git diff --cached -U0 | grep -qE '^\+.*(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|[?&]sig=[A-Za-z0-9%]{20,})'; then
  git reset -q -- $files
  say "Auto-push skipped: the changes look like they contain an API key or signed URL. Review and commit by hand."
  exit 0
fi

count=$(printf '%s\n' "$files" | wc -l | tr -d ' ')
list=$(printf '%s\n' "$files" | head -5 | paste -sd ',' - | sed 's/,/, /g')
[ "$count" -gt 5 ] && list="$list, +$((count - 5)) more"

git commit -q -m "Update $list" -m "Auto-committed by Claude Code Stop hook.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || { say "Auto-commit failed."; exit 0; }

if out=$(git push -q origin "$branch" 2>&1); then
  say "Auto-pushed $count file(s) to origin/$branch: $list"
else
  say "Committed $count file(s) but push to origin/$branch failed: $(printf '%s' "$out" | tail -1)"
fi
exit 0
