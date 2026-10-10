#!/usr/bin/env bash
# Installs howto from this repository: builds its Python environment,
# downloads Playwright's Chromium (about 300 MB), and links the commands and
# the authoring skill into $HOME. Idempotent: safe to run again.
#
# The environment is built on a uv-managed Python, so it does not depend on
# the distribution's interpreter or on one from a package manager. The package
# is installed editable, so an edit in this repository is live without a
# reinstall.
#
# The skill is linked for Claude Code, and only when Claude Code is there:
# ~/.claude is not this script's to make. pi sees the skill in that folder
# too when its settings list it ("skills": ["~/.claude/skills"]). A second
# link in pi's own skills folder would give pi the skill twice.
#
# HOWTO_VENV, HOWTO_BIN_DIR, HOWTO_CLAUDE_SKILLS and HOWTO_SKIP_BROWSER exist
# so that install.test.sh can run this in a sandbox.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HOWTO_VENV:-$HOME/.local/share/howto/venv}"
BIN_DIR="${HOWTO_BIN_DIR:-$HOME/.local/bin}"
CLAUDE_SKILLS="${HOWTO_CLAUDE_SKILLS:-}"

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

# The two speech commands as well: HOWTO_TTS names one of them by its name.
for name in howto howto-tts-audiocpp howto-tts-kokoro; do
  link "$VENV/bin/$name" "$BIN_DIR/$name"
done
if [ -z "$CLAUDE_SKILLS" ] && [ -d "$HOME/.claude" ]; then
  CLAUDE_SKILLS="$HOME/.claude/skills"
fi
if [ -n "$CLAUDE_SKILLS" ]; then
  link "$REPO/skill" "$CLAUDE_SKILLS/howto-video"
else
  echo "howto-install: Claude Code was not found (no ~/.claude), so the skill is not linked."
  echo "howto-install: give your agent $REPO/skill/SKILL.md, which says how to write a storyboard."
fi

echo "howto-install: done. Try: howto --help"
