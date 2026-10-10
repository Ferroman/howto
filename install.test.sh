#!/usr/bin/env bash
# Sandbox test for install.sh. A fake `uv` stands in for the real one: it logs
# its arguments and, for `uv venv`, creates the three programs install.sh
# expects inside the environment. Nothing outside the sandbox is touched.
#
# usage: bash install.test.sh
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0
assert() { if eval "$2"; then echo "ok   - $1"; else echo "FAIL - $1"; fail=1; fi; }

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home" LOG="$SANDBOX/calls.log"
mkdir -p "$HOME" "$SANDBOX/bin"
unset HOWTO_VENV HOWTO_BIN_DIR HOWTO_CLAUDE_SKILLS HOWTO_SKIP_BROWSER

cat > "$SANDBOX/bin/uv" <<'EOF'
#!/usr/bin/env bash
echo "uv $*" >> "$LOG"
if [ "$1" = venv ]; then
  mkdir -p "$2/bin"
  for name in python howto howto-tts-audiocpp howto-tts-kokoro playwright; do
    printf '#!/usr/bin/env bash\necho "%s $*" >> "$LOG"\n' "$name" > "$2/bin/$name"
    chmod +x "$2/bin/$name"
  done
fi
exit 0
EOF
chmod +x "$SANDBOX/bin/uv"
REAL_PATH="$PATH"
export PATH="$SANDBOX/bin:$PATH"

VENV="$HOME/.local/share/howto/venv"
run() { out="$(bash "$REPO/install.sh" 2>&1)"; rc=$?; }
calls() { grep -c -- "$1" "$LOG" 2>/dev/null || true; }

# --- a machine without Claude Code -------------------------------------------
# ~/.claude belongs to another program. The installer links the skill into it
# and does not make it.
run
assert "a run without Claude Code succeeds" '[ "$rc" = 0 ]'
assert "no folder is made for Claude Code" '[ ! -e "$HOME/.claude" ]'
assert "the message says where the skill is" '[[ "$out" == *"$REPO/skill/SKILL.md"* ]]'
assert "the command is linked all the same" '[ "$(readlink "$HOME/.local/bin/howto")" = "$VENV/bin/howto" ]'
rm -rf "$HOME/.local" "$LOG"

# --- a first install ----------------------------------------------------------
mkdir "$HOME/.claude"
run
assert "first run succeeds" '[ "$rc" = 0 ]'
assert "the environment is built on a uv-managed Python 3.13" \
  'grep -qx "uv venv $VENV --managed-python --python 3.13" "$LOG"'
assert "the package is installed editable from this repository" \
  'grep -q "^uv pip install .*-e $REPO\$" "$LOG"'
assert "Chromium is downloaded" 'grep -qx "playwright install chromium" "$LOG"'
assert "the command is linked" '[ "$(readlink "$HOME/.local/bin/howto")" = "$VENV/bin/howto" ]'
assert "the skill is linked for Claude Code" \
  '[ "$(readlink "$HOME/.claude/skills/howto-video")" = "$REPO/skill" ]'
# HOWTO_TTS names a speech command by its name, so both have to be on PATH.
for name in howto-tts-audiocpp howto-tts-kokoro; do
  assert "the speech command $name is linked" '[ "$(readlink "$HOME/.local/bin/$name")" = "$VENV/bin/$name" ]'
done

# --- a second run, on a machine with pi --------------------------------------
# pi loads ~/.claude/skills through its settings, and it skips whatever an
# ignore file in its own skills folder names. A link there would be a
# duplicate or invisible, so the installer leaves that folder alone.
mkdir -p "$HOME/.pi/agent/skills"
run
assert "second run succeeds" '[ "$rc" = 0 ]'
assert "the environment is not rebuilt" '[ "$(calls "^uv venv ")" = 1 ]'
assert "the skills folder of pi is left alone" '[ -z "$(ls -A "$HOME/.pi/agent/skills")" ]'
assert "the links are unchanged" \
  '[ "$(readlink "$HOME/.local/bin/howto")" = "$VENV/bin/howto" ] && [ "$(readlink "$HOME/.claude/skills/howto-video")" = "$REPO/skill" ]'

# --- the browser download can be skipped ------------------------------------
before="$(calls "^playwright install")"
HOWTO_SKIP_BROWSER=1 run
assert "HOWTO_SKIP_BROWSER skips the download" '[ "$rc" = 0 ] && [ "$(calls "^playwright install")" = "$before" ]'

# --- a real file in the way is left alone -----------------------------------
rm "$HOME/.local/bin/howto"
echo "mine" > "$HOME/.local/bin/howto"
run
assert "a file in the way stops the installer" '[ "$rc" != 0 ]'
assert "that file is untouched" '[ "$(cat "$HOME/.local/bin/howto")" = mine ]'
assert "the message names the path" '[[ "$out" == *"$HOME/.local/bin/howto exists and is not a link"* ]]'

# --- no uv -------------------------------------------------------------------
mkdir "$SANDBOX/nouv"
ln -s "$(PATH="$REAL_PATH" command -v dirname)" "$SANDBOX/nouv/dirname"
out="$(PATH="$SANDBOX/nouv" "$BASH" "$REPO/install.sh" 2>&1)"; rc=$?
assert "without uv the installer stops and says why" '[ "$rc" != 0 ] && [[ "$out" == *"uv is not on PATH"* ]]'

if [ "$fail" = 0 ]; then echo "ALL TESTS PASSED"; else echo "SOME TESTS FAILED"; fi
exit "$fail"
