#!/usr/bin/env bash
# The local bee's launcher against this machine's real Docker, before a launcher PR merges: what test_local.sh's
# stand-in docker never runs. It builds the tool's image as the launcher does, if this machine has not built it yet,
# and runs `local.sh check` for a public project of the hive: the image, hive.py in it, the gate, Docker's paths.
#
# - The launcher and the protocol are this clone's HEAD (commit first), in a home of the smoke's own, removed after:
#   nothing of ~/.hive is read or written.
# - No credential is read. The launcher clears every GIT_ variable, so the smoke puts a git of its own first on PATH:
#   this machine's git with its credential helpers reset (-c credential.helper=), which asks no helper and finds no
#   token. The account then comes from a stand-in gh that names a login of its own (hive-smoke). check pushes nothing.
#   (So the token's way, git's credential sent to api.github.com by curl, is not run here.)
# - It reaches GitHub's public pages for the project, through the launcher's gate, as a volunteer's check does.
# - The containers are the launcher's own (hive-egress-<pid>-<n>, and throwaway ones), on its network hive-inner.
#
# usage: bash tools/hive/smoke_local.sh [owner/name]   (default Bee-ruche/minizBee)
set -u
PROJECT="${1:-Bee-ruche/minizBee}"
[[ $PROJECT =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]] || { echo "smoke: the project as owner/name"; exit 2; }
here=$(cd "$(dirname "$0")/../.." && pwd -P) || exit 2
command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1 || { echo "smoke: Docker is not running here"; exit 2; }
command -v timeout >/dev/null 2>&1 || { echo "smoke: timeout is not on PATH"; exit 2; }

home=$(mktemp -d "${TMPDIR:-/tmp}/hive-smoke.XXXXXX") || exit 2
trap 'rm -rf "$home"' EXIT
mkdir -p "$home/bin" "$home/desk" || exit 2
# No settings of this machine's for git: none of its credential helpers, nothing from the environment.
quiet_git() { env -u GIT_CONFIG_COUNT -u GIT_CONFIG_PARAMETERS GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git "$@"; }
head=$(quiet_git -C "$here" rev-parse --verify HEAD) || exit 2
quiet_git clone --quiet --no-checkout "$here" "$home/.hive/protocol" && quiet_git -C "$home/.hive/protocol" checkout --quiet --detach "$head" \
  || { echo "smoke: the protocol could not be copied from $here"; exit 2; }
cat > "$home/bin/gh" <<'GH'
#!/bin/sh
[ "$*" = "api --hostname github.com user --jq .login" ] && { echo hive-smoke; exit 0; }
exit 1
GH
chmod +x "$home/bin/gh"
real_git=$(command -v git) && case "$real_git" in *"'"*) false ;; /*) true ;; *) false ;; esac \
  || { echo "smoke: git is not on PATH by a plain place"; exit 2; }
printf '#!/bin/sh\nexec '\''%s'\'' -c credential.helper= "$@"\n' "$real_git" > "$home/bin/git" && chmod +x "$home/bin/git" || exit 2
# Before the launcher: that git is the one found, and it finds no password for github.com (what it would say is
# never shown: only whether a password line came back).
mkdir -p "$home/ask" || exit 2
[ "$(PATH="$home/bin:$PATH" command -v git)" = "$home/bin/git" ] \
  && ! (cd "$home/ask" && printf 'protocol=https\nhost=github.com\n\n' | PATH="$home/bin:$PATH" GIT_CEILING_DIRECTORIES="$home/ask" \
        GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never timeout 30 git -c core.askPass= credential fill 2>/dev/null | grep -q '^password=') \
  || { echo "smoke: this machine's git would still give a credential: nothing was run"; exit 2; }

# Docker's settings from their usual place, as the launcher reads them: on Windows, the user's profile (no HOME of
# Docker's); elsewhere ~/.docker, which the smoke's home shows through a link.
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) ;; *) [ ! -d "${HOME}/.docker" ] || ln -s "${HOME}/.docker" "$home/.docker" || exit 2 ;; esac

echo "smoke: local.sh check --project $PROJECT, at $head"
said=$(cd "$home/desk" && HOME="$home" PATH="$home/bin:$PATH" \
  env -u DOCKER_CONFIG -u GIT_CONFIG_COUNT -u GIT_CONFIG_PARAMETERS -u GIT_ASKPASS -u SSH_ASKPASS -u GH_TOKEN -u GITHUB_TOKEN -u GH_HOST -u GH_CONFIG_DIR \
  GCM_INTERACTIVE=never \
  timeout 1800 bash "$home/.hive/protocol/tools/hive/local.sh" check --project "$PROJECT" 2>&1)
code=$?
printf '%s\n' "$said"
if [ "$code" -eq 0 ] && printf '%s\n' "$said" | grep -q '^NAMES-HELD [0-9][0-9]*$' && printf '%s\n' "$said" | grep -qx 'LOCAL login hive-smoke'; then
  echo "smoke: PASSED"
else
  [ -f "$home/.hive/build-tool.log" ] && { echo "smoke: the tool's build log:"; cat "$home/.hive/build-tool.log"; }
  echo "smoke: FAILED (exit $code)"
  exit 1
fi
