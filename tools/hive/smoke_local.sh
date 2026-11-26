#!/usr/bin/env bash
# The local bee's launcher against this machine's real Docker, before a launcher PR merges: what test_local.sh's
# stand-in docker never runs. It builds the tool's image as the launcher does, if this machine has not built it yet,
# and runs `local.sh check` for a public project of the hive: the image, hive.py in it, the gate, Docker's paths.
#
# - The launcher and the protocol are this clone's HEAD (commit first), in a home of the smoke's own, removed after:
#   nothing of ~/.hive is read or written.
# - No credential is read. git sees no settings of this machine's (no helper), and the account comes from a stand-in
#   gh that names a login of its own (hive-smoke). check pushes nothing.
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

echo "smoke: local.sh check --project $PROJECT, at $head"
said=$(cd "$home/desk" && DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}" HOME="$home" PATH="$home/bin:$PATH" \
  env -u GIT_CONFIG_COUNT -u GIT_CONFIG_PARAMETERS -u GIT_ASKPASS -u SSH_ASKPASS -u GH_TOKEN -u GITHUB_TOKEN -u GH_HOST -u GH_CONFIG_DIR \
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GCM_INTERACTIVE=never \
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
