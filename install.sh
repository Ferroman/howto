#!/usr/bin/env bash
# Installs howto from this repository: builds its Python environment,
# downloads Playwright's Chromium, and links the command and the authoring
# skill into $HOME. Idempotent: safe to run again.
#
# The environment is built on a uv-managed Python, so it does not depend on
# linuxbrew's or the distribution's interpreter. The package is installed
# editable, so an edit in this repository is live without a reinstall.
#
# The dotfiles repository carries a thin scripts/howto-install.sh wrapper that
# runs this script. It is deliberately not part of the dotfiles install.sh,
# because of the browser download.
#
# HOWTO_VENV, HOWTO_BIN_DIR, HOWTO_CLAUDE_SKILLS, HOWTO_PI_SKILLS and
# HOWTO_SKIP_BROWSER exist so that install.test.sh can run this in a sandbox.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HOWTO_VENV:-$HOME/.local/share/howto/venv}"
BIN_DIR="${HOWTO_BIN_DIR:-$HOME/.local/bin}"
CLAUDE_SKILLS="${HOWTO_CLAUDE_SKILLS:-$HOME/.claude/skills}"
PI_SKILLS="${HOWTO_PI_SKILLS:-$HOME/.pi/agent/skills}"

command -v uv >/dev/null 2>&1 || { echo "howto-install: uv is not on PATH" >&2; exit 1; }

[ -x "$VENV/bin/python" ] || uv venv "$VENV" --managed-python --python 3.13
VIRTUAL_ENV="$VENV" uv pip install --quiet -e "$REPO"

if [ -z "${HOWTO_SKIP_BROWSER:-}" ]; then
  "$VENV/bin/playwright" install chromium
fi

# link <target> <path>: replaces a link, and refuses to replace anything else.
link() {
  local target="$1" path="$2"
  mkdir -p "$(dirname "$path")"
  if [ -L "$path" ]; then
    rm "$path"
  elif [ -e "$path" ]; then
    echo "howto-install: $path exists and is not a link; leaving it" >&2
    return 1
  fi
  ln -s "$target" "$path"
}

link "$VENV/bin/howto" "$BIN_DIR/howto"
link "$REPO/skill" "$CLAUDE_SKILLS/howto-video"
# pi's skills folder is created by pi (and, on the workstation, is a link into
# the dotfiles repository). Without it there is no pi to install a skill for.
if [ -d "$PI_SKILLS" ]; then
  link "$REPO/skill" "$PI_SKILLS/howto-video"
else
  echo "howto-install: $PI_SKILLS not found; skipped the pi skill"
fi

echo "howto-install: done. Try: howto --help"
