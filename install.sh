#!/usr/bin/env bash
# BetterPrompt installer. Works BOTH from a clone and piped (curl ... | bash).
set -eu

REPO="shovexxx/Betterhermesprompt"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
ID="better-prompt"

msg() { printf '\033[36m[*]\033[0m %s\n' "$*"; }

msg "installing plugin to $HERMES/plugins/$ID"
mkdir -p "$HERMES/plugins/$ID"

SRC="${BASH_SOURCE[0]:-}"
if [ -n "$SRC" ] && [ -f "$(dirname "$SRC")/plugin.yaml" ]; then
  # local clone — copy the tree
  dir="$(cd "$(dirname "$SRC")" && pwd)"
  msg "copying from local checkout: $dir"
  cp -r "$dir"/plugin.yaml "$dir"/__init__.py "$dir"/engine.py "$dir"/cli.py "$dir"/skills "$dir"/dashboard "$dir"/desktop "$HERMES/plugins/$ID/" 2>/dev/null || true
else
  # piped from curl — download from GitHub
  msg "downloading from github.com/$REPO"
  base="https://raw.githubusercontent.com/$REPO/main"
  for f in plugin.yaml __init__.py engine.py cli.py; do
    curl -fsSL "$base/$f" -o "$HERMES/plugins/$ID/$f"
  done
  mkdir -p "$HERMES/plugins/$ID/skills/prompt-audit" "$HERMES/plugins/$ID/dashboard" "$HERMES/plugins/$ID/desktop"
  curl -fsSL "$base/skills/prompt-audit/SKILL.md" -o "$HERMES/plugins/$ID/skills/prompt-audit/SKILL.md"
  curl -fsSL "$base/dashboard/manifest.json" -o "$HERMES/plugins/$ID/dashboard/manifest.json"
  curl -fsSL "$base/dashboard/plugin_api.py" -o "$HERMES/plugins/$ID/dashboard/plugin_api.py"
  curl -fsSL "$base/desktop/plugin.js" -o "$HERMES/plugins/$ID/desktop/plugin.js"
fi

msg "installing TUI widget (optional) to $HERMES/tui-widgets"
mkdir -p "$HERMES/tui-widgets"
if [ -f "$(dirname "$SRC" 2>/dev/null)/tui/auditprompt.mjs" ] 2>/dev/null; then
  cp "$(dirname "$SRC")/tui/auditprompt.mjs" "$HERMES/tui-widgets/auditprompt.mjs"
else
  curl -fsSL "$base/tui/auditprompt.mjs" -o "$HERMES/tui-widgets/auditprompt.mjs" || true
fi

msg "done. Enable the plugin with:  hermes plugins enable $ID"
msg "In Hermes Desktop: Capabilities → Plugins → enable BetterPrompt, then ⌘K → Reload desktop plugins."
msg "Try it now in a shell:  python3 -m cli 'fix teh website please'   (from $HERMES/plugins/$ID)"
