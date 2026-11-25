#!/usr/bin/env bash
# The tests of the local bee's launcher (tools/hive/local.sh), on Linux, with git and a stub docker of their own.
#
# The launcher is tested on a copy of itself that differs in two lines only: GitHub is a folder of bare repositories,
# and git may read such a folder (FILE_PROTOCOL). The stub docker answers as Docker would and plays each container's
# part from the case's own fixtures: the tool prints what the case says and writes the case's hand-over into the slot
# the launcher mounts; hand-over-check says CHECKED with the SHA-256 of the files the launcher mounts, unless the case
# says otherwise. The hand-overs are real: commits and bundles made with git, pushed by the launcher's own git into
# the bare fork. What hive.py itself does is test_hive.py's (TestTheHandOver, TestTheHandOverCheck…).
#
# Every refusal of the launcher has its case, and each case says what must hold after it: the exit code, the line,
# the fork unchanged, the slot empty. Valid hand-overs drawn at random (task ids, the member's case) are pushed among
# them, and one fixed refusal lies at a random place among the drawn ones. Each run of the launcher is under timeout;
# the temporary folder is removed whatever happens.
#
# usage: bash tools/hive/test_local.sh   (from the root of a tree of the hive's repository; prints one line per case,
# then « N passed, M failed »; exit 0 only if every case passed)
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd -P)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
PASSED=0 FAILED=0

# ---------------------------------------------------------------------------------------------------------------
# The world: a home, the protocol, GitHub as bare folders, the launcher's copy, the stub docker.

export HOME="$T/home"
mkdir -p "$HOME" "$T/bin" "$T/desk" "$T/github/Bee-ruche" "$T/github/alice" "$T/stub" "$T/h"
export GIT_CONFIG_NOSYSTEM=1
git config --global init.defaultBranch main
git config --global user.name tester
git config --global user.email tester@example.com
cp "$HOME/.gitconfig" "$T/gitconfig"

PROTOCOL="$HOME/.hive/protocol"
mkdir -p "$PROTOCOL/tools/hive"
cp "$ROOT/tools/hive/hive.py" "$ROOT/tools/hive/Dockerfile" "$ROOT/tools/hive/egress.py" "$PROTOCOL/tools/hive/"
git -C "$PROTOCOL" init -q && git -C "$PROTOCOL" add -A && git -C "$PROTOCOL" commit -q -m protocol

LAUNCHER="$T/local.sh"
sed -e "s|^GITHUB=\"https://github.com\"\$|GITHUB=\"file://$T/github\"|" -e 's|^FILE_PROTOCOL="never"$|FILE_PROTOCOL="always"|' \
  "$ROOT/tools/hive/local.sh" > "$LAUNCHER"
if [ "$(diff "$ROOT/tools/hive/local.sh" "$LAUNCHER" | grep -c '^>')" -ne 2 ]; then
  echo "the launcher's copy differs in other lines than its two constants"; exit 2
fi

# The project, its fork, and a scratch clone where the hand-overs are made.
git init -q --bare "$T/github/Bee-ruche/toy"
MAKER="$T/maker"
git init -q "$MAKER"
printf 'int x;\n' > "$MAKER/x.c"
git -C "$MAKER" add -A && git -C "$MAKER" commit -q -m one
printf 'int y;\n' > "$MAKER/y.c"
git -C "$MAKER" add -A && git -C "$MAKER" commit -q -m two
git -C "$MAKER" push -q "$T/github/Bee-ruche/toy" HEAD:refs/heads/main
BASE=$(git -C "$MAKER" rev-parse HEAD)
git clone -q --bare "$T/github/Bee-ruche/toy" "$T/github/alice/toy"
FORK="$T/github/alice/toy"
EMPTY_TREE=4b825dc642cb6eb9a060e54bf8d69288fbee4904

CLONE="$HOME/.hive/work/alice/toy"
mkdir -p "$CLONE" "$HOME/.hive/state/Bee-ruche/toy"
git -C "$CLONE" init -q
git -C "$HOME/.hive/state/Bee-ruche/toy" init -q
SLOT="$HOME/.hive/outbox/Bee-ruche/toy"

cat > "$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
# The tests' docker: Docker's answers, and each container's part played from the case's fixtures ($STUB_*).
set -u
S="$STUB_DIR"
printf '%s\n' "$*" >> "$S/calls"
case "${1:-}" in
  info) [ -z "${STUB_DOWN:-}" ] || exit 1; echo "${STUB_OSTYPE:-linux}"; exit 0 ;;
  version) echo 27.3.1; exit 0 ;;
  image) [ -f "$S/built" ]; exit $? ;;
  build) [ "${*: -1}" != - ] || cat > /dev/null; [ -z "${STUB_BUILD_FAILS:-}" ] || exit 1; touch "$S/built"; exit 0 ;;
  network)
    case "$2" in
      inspect)
        case "$*" in
          *Internal*) echo "${STUB_INTERNAL:-true}" ;;
          *Containers*) echo "${STUB_INNER:-hive-egress}" ;;
        esac
        exit 0 ;;
      *) exit 0 ;;
    esac ;;
  rm) exit 0 ;;
  port) printf '%s' "${STUB_PORT:-}"; exit 0 ;;
  inspect) case "$*" in *Aliases*) echo "${STUB_ALIASES:-}" ;; esac; exit 0 ;;
  run) shift ;;
  *) exit 0 ;;
esac
role="" ; : > "$S/mounts"
while [ $# -gt 0 ]; do
  case "$1" in
    --rm|-d|--read-only) shift ;;
    --label) role="${2#hive.role=}"; shift 2 ;;
    --mount) printf '%s\n' "$2" >> "$S/mounts"; shift 2 ;;
    --*|-e|-w) shift 2 ;;
    *) break ;;
  esac
done
shift  # the image
source_of() { sed -n "s|^type=bind,source=\([^,]*\),target=$1\(,readonly\)\{0,1\}\$|\1|p" "$S/mounts" | head -1; }
cp "$S/mounts" "$S/mounts.$role"
printf '%s\n' "$*" > "$S/args.$role"
case "$role" in
  probe) echo "${STUB_OWNER:-1000:1000}"; echo $(( $(date -u +%s) + ${STUB_SKEW:-0} )) ;;
  dns) exit "${STUB_DNS:-2}" ;;
  egress) exit 0 ;;
  names) [ -z "${STUB_NAMES_REFUSE:-}" ] || { echo "hive: the project's tip holds two names…" >&2; exit 2; }; echo "NAMES-HELD 3" ;;
  tool)
    outbox=$(source_of /hive/outbox)
    if [ -n "${STUB_HANDOVER:-}" ]; then cp -P "$STUB_HANDOVER"/* "$outbox"/ 2>/dev/null; fi
    [ -z "${STUB_TOOL_OUT:-}" ] || cat "$STUB_TOOL_OUT"
    exit "${STUB_TOOL_CODE:-0}" ;;
  check)
    folder=$(source_of /hive/handover)
    if [ -n "${STUB_CHECK_OUT:-}" ]; then cat "$STUB_CHECK_OUT"; exit "${STUB_CHECK_CODE:-0}"; fi
    branch=$(sed -n 's/^branch //p' "$folder/handover.txt")
    txt=$(sha256sum "$folder/handover.txt" | cut -d' ' -f1)
    if grep -qx 'action withdraw' "$folder/handover.txt"; then echo "CHECKED delete $branch $txt"
    else echo "CHECKED $(sed -n 's/^commit //p' "$folder/handover.txt") $txt $(sha256sum "$folder/handover.bundle" | cut -d' ' -f1)"; fi ;;
  sandbox)
    work=$(source_of /work)
    [ -z "${STUB_SANDBOX_MAKES:-}" ] || mkdir -p "$work/$STUB_SANDBOX_MAKES"
    exit "${STUB_SANDBOX_CODE:-0}" ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$T/bin/docker"
export STUB_DIR="$T/stub"
BASE_PATH="$T/bin:/usr/local/bin:/usr/bin:/bin"

# ---------------------------------------------------------------------------------------------------------------
# Hand-overs, made as the tool makes them.

ADDRESS="alice@users.noreply.github.com"
commit_tree() {  # <tree> <message> [<parent>…]: a commit of the scratch clone, signed as the tool signs (EMAIL to say otherwise)
  local tree="$1" message="$2" parents=() p
  shift 2
  for p in "$@"; do parents+=(-p "$p"); done
  printf '%s' "$message" | GIT_AUTHOR_NAME=alice GIT_AUTHOR_EMAIL="${EMAIL:-$ADDRESS}" GIT_COMMITTER_NAME=alice GIT_COMMITTER_EMAIL="${EMAIL:-$ADDRESS}" \
    git -C "$MAKER" commit-tree "$tree" ${parents[@]+"${parents[@]}"}
}
ask_message() { printf 'Hive ready (2026-11-25T10:00:00Z)\n\nHive-Action: ready\nHive-Member: %s\nHive-Tier: 3\n' "${1:-alice}"; }
release_message() { printf 'Hive release: %s (2026-11-25T10:00:00Z)\n\nHive-Task: %s\nHive-Action: release\nHive-Deal: 2026-11-25T09:00:00Z\nHive-Member: alice\nHive-Because: out_of_reach\n' "$1" "$1"; }
duty_message() { printf 'Hive duty: cut (2026-11-25T10:00:00Z)\n\nHive-Action: duty\nHive-Member: alice\nHive-Role: cut\n'; }
duty_release_message() { printf 'Hive duty release: cut (2026-11-25T10:00:00Z)\n\nHive-Action: release\nHive-Member: alice\nHive-Role: cut\nHive-Deal: 2026-11-25T09:00:00Z\nHive-Because: cannot_run\n'; }
submit_message() { printf 'Hive submit: %s\n\nHive-Task: %s\nHive-Action: submit\nHive-Deal: 2026-11-25T09:00:00Z\nHive-Member: %s\n' "$1" "$1" "${2:-alice}"; }

N=0
hand_over() {  # <action> <branch> <commit> [<base> <project-branch> <task> | <task>]: a folder of hand-over; prints its path
  local dir
  dir=$(mktemp -d "$T/h/XXXXXX")
  local base=""
  [ $# -ge 6 ] && base="$4"
  if [ -n "$3" ]; then
    git -C "$MAKER" update-ref "refs/heads/$2" "$3"
    git -C "$MAKER" bundle create -q "$dir/handover.bundle" "refs/heads/$2" ${base:+"^$base"} 2>/dev/null
    git -C "$MAKER" update-ref -d "refs/heads/$2"
  fi
  {
    printf 'hive-handover 1\naction %s\nbranch %s\n' "$1" "$2"
    [ -z "$3" ] || printf 'commit %s\n' "$3"
    if [ $# -ge 6 ]; then printf 'base %s\nproject-branch %s\ntask %s\n' "$4" "$5" "$6"; elif [ $# -eq 4 ]; then printf 'task %s\n' "$4"; fi
  } > "$dir/handover.txt"
  printf '%s' "$dir"
}
said() {  # <lines…>: a file of the tool's output; prints its path
  local file
  file=$(mktemp "$T/h/said.XXXXXX")
  printf '%s\n' "$@" > "$file"
  printf '%s' "$file"
}
ask_commit() { commit_tree "$EMPTY_TREE" "$(ask_message "${1:-alice}")"; }
candidate() {  # <task> [<member>]: the marker of a candidate on the project's commit, its work changing one file
  local tree work
  printf 'int z;\n' > "$MAKER/z.c"
  git -C "$MAKER" add z.c
  tree=$(git -C "$MAKER" write-tree)
  git -C "$MAKER" reset -q --hard "$BASE"
  work=$(commit_tree "$tree" "the work
" "$BASE")
  commit_tree "$tree" "$(submit_message "$1" "${2:-alice}")" "$work"
}

# ---------------------------------------------------------------------------------------------------------------
# A case: the launcher run from the session's folder, under timeout, its output and what it left.

OUT="" ERR="" CODE=0
launch() {  # <words…>: runs the launcher; sets OUT, ERR, CODE
  : > "$STUB_DIR/calls"
  (cd "${HERE:-$T/desk}" && PATH="${CASE_PATH:-$BASE_PATH}" timeout 120 bash "$LAUNCHER" "$@" < /dev/null > "$T/out" 2> "$T/err")
  CODE=$?
  OUT=$(cat "$T/out")
  ERR=$(cat "$T/err")
}
fork_ref() { git -C "$FORK" rev-parse --verify --quiet "refs/heads/$1"; }
slot_empty() { [ -z "$(ls -A "$SLOT" 2>/dev/null)" ]; }
ran() { grep -q "^run .*hive.role=$1" "$STUB_DIR/calls"; }
reset_world() {
  rm -rf "$SLOT"
  for ref in $(git -C "$FORK" for-each-ref --format='%(refname)' refs/heads/hive); do git -C "$FORK" update-ref -d "$ref"; done
  cp "$T/gitconfig" "$HOME/.gitconfig"
  rm -f "$HOME/.hive/started/Bee-ruche/toy"
}

check() {  # <name> <condition…>: one line, passed or FAILED with what was seen
  local name="$1"
  shift
  if "$@"; then PASSED=$((PASSED + 1)); echo "passed: $name"
  else FAILED=$((FAILED + 1)); echo "FAILED: $name (exit $CODE; out: ${OUT:0:300}; err: ${ERR:0:300})"; fi
}
refused() {  # <exit code> <the line's beginning>: the launcher ended on that one line
  [ "$CODE" -eq "$1" ] && [ "$(printf '%s\n' "$ERR" | grep -c .)" -eq 1 ] && case "$ERR" in "hive: $2"*) true ;; *) false ;; esac
}
nothing_ran() { ! grep -q '^run ' "$STUB_DIR/calls"; }
untouched() { [ -z "$(git -C "$FORK" for-each-ref refs/heads/hive)" ] && slot_empty; }

READY=(hive ready --project Bee-ruche/toy --login alice)
case_ready() {  # <name> <hand-over folder> <condition…>: ready, its tool handing over that folder
  local name="$1"
  reset_world
  STUB_HANDOVER="$2" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready" "THEN: stop here.")" launch "${READY[@]}"
  shift 2
  check "$name" "$@"
}

# ---------------------------------------------------------------------------------------------------------------
# Before any container: the command line, the session's place, the machine.

reset_world
for words in "doctor --project Bee-ruche/toy" "hive doctor --project Bee-ruche/toy --login alice" "hive admit --project Bee-ruche/toy --login alice"; do
  launch $words
  check "refused: local.sh $words" eval 'refused 2 "local.sh" && nothing_ran'
done
for option in --state --hand-over --upstream-url --needs-home --needs-shown --no-push --hand --st --proj; do
  launch hive next --project Bee-ruche/toy --login alice "$option" /tmp
  check "refused: the caller's $option" eval 'refused 2 "$option is not an option of local.sh hive next" && nothing_ran'
done
launch hive next --project=Bee-ruche/toy --login alice
check "refused: an option and its value in one word" eval 'refused 2 "give each option and its value as two words" && nothing_ran'
launch hive next --project Bee-ruche/toy --login alice stray
check "refused: a word that is no option" eval 'refused 2 "an option was expected" && nothing_ran'
launch hive next --project Bee-ruche/toy --login alice --project Other/toy
check "refused: --project twice" eval 'refused 2 "--project given twice" && nothing_ran'
for project in "Bee-ruche" "Bee-ruche/toy/x" "-x/toy" "Bee-ruche/.." "Bee-ruche/a b"; do
  launch hive next --project "$project" --login alice
  check "refused: the project '$project'" eval 'refused 2 "--project:" && nothing_ran'
done
launch hive next --project Bee-ruche/toy --login "al ice"
check "refused: a login of another form" eval 'refused 2 "--login:" && nothing_ran'
launch hive next --project Bee-ruche/toy --login alice --fork ..
check "refused: a fork named .." eval 'refused 2 "--fork:" && nothing_ran'
launch hive next --project Bee-ruche/toy --login bee-ruche
check "refused: the project's own repository as the fork" eval 'refused 2 "the fork named is the project" && nothing_ran'
launch hive submit --project Bee-ruche/toy --login alice --task Toy-1 --deal x
check "refused: a task of another form" eval 'refused 2 "--task:" && nothing_ran'
launch sandbox --project Bee-ruche/toy --login alice
check "refused: the sandbox with no command" eval 'refused 2 "local.sh sandbox runs the command given after --" && nothing_ran'

HERE="$CLONE" launch hive next --project Bee-ruche/toy --login alice
check "refused: the session in the clone" eval 'refused 2 "this session" && nothing_ran'
mkdir -p "$CLONE/src"
HERE="$CLONE/src" launch hive next --project Bee-ruche/toy --login alice
check "refused: the session inside the clone" eval 'refused 2 "this session" && nothing_ran'
HERE="$HOME" launch hive next --project Bee-ruche/toy --login alice
check "refused: the session above the clone" eval 'refused 2 "this session" && nothing_ran'
CASE_PATH="bin:$BASE_PATH" launch hive next --project Bee-ruche/toy --login alice
check "refused: a relative entry in the PATH" eval 'refused 2 "the PATH holds a relative entry" && nothing_ran'
CASE_PATH="$CLONE/src:$BASE_PATH" launch hive next --project Bee-ruche/toy --login alice
check "refused: a folder of the clone in the PATH" eval 'refused 2 "the PATH holds a folder of the clone" && nothing_ran'
mkdir -p "$T/nodocker"
ln -s "$(command -v git)" "$T/nodocker/git"
CASE_PATH="$T/nodocker:/usr/bin:/bin" launch hive next --project Bee-ruche/toy --login alice
check "refused: no docker" eval '{ refused 2 "docker is not on this machine" || [ -x /usr/bin/docker ]; }'
STUB_DOWN=1 launch hive next --project Bee-ruche/toy --login alice
check "refused: Docker does not answer" eval 'refused 2 "Docker does not answer" && nothing_ran'
STUB_OSTYPE=windows launch hive next --project Bee-ruche/toy --login alice
check "refused: Windows containers" eval 'refused 2 "Docker runs windows containers" && nothing_ran'
rm -f "$STUB_DIR/built"
STUB_BUILD_FAILS=1 launch hive next --project Bee-ruche/toy --login alice
check "refused: the image cannot be built" eval 'refused 2 "Docker could not build" && nothing_ran'
launch hive next --project Bee-ruche/toy --login alice
check "the image built from the protocol's commit, tagged by its Dockerfile's blob id" \
  grep -q "^build --quiet -t hive-tool:$(git -C "$PROTOCOL" rev-parse HEAD:tools/hive/Dockerfile) -\$" "$STUB_DIR/calls"
STUB_SKEW=120 launch hive next --project Bee-ruche/toy --login alice
check "refused: Docker's clock two minutes away" eval 'refused 2 "Docker'"'"'s clock is 120 seconds away" && ! ran tool'
mv "$PROTOCOL" "$T/protocol-aside"
launch hive next --project Bee-ruche/toy --login alice
check "refused: no protocol" eval 'refused 2 "the hive'"'"'s protocol is not at" && nothing_ran'
mv "$T/protocol-aside" "$PROTOCOL"

# The gate.
STUB_INTERNAL=false launch hive next --project Bee-ruche/toy --login alice
check "refused: a network with a route out" eval 'refused 2 "the network hive-inner has a route out" && ! ran tool'
STUB_PORT="3128/tcp -> 0.0.0.0:3128" launch hive next --project Bee-ruche/toy --login alice
check "refused: the gate's port published" eval 'refused 2 "the hive'"'"'s gate has a port published" && ! ran tool'
STUB_INNER="hive-egress github.com" launch hive next --project Bee-ruche/toy --login alice
check "refused: a container named github.com on the network" eval 'refused 2 "a container on the network hive-inner answers to github.com" && ! ran tool'
STUB_INNER="hive-egress other" STUB_ALIASES="api.GitHub.com." launch hive next --project Bee-ruche/toy --login alice
check "refused: a container aliased as a name of GitHub's" eval 'refused 2 "a container on the network hive-inner answers to api.GitHub.com." && ! ran tool'
STUB_DNS=0 launch hive next --project Bee-ruche/toy --login alice
check "refused: an outside name resolves from the network" eval 'refused 2 "a name outside this machine resolves" && ! ran tool'

# ---------------------------------------------------------------------------------------------------------------
# What the tool is given.

reset_world
STUB_TOOL_OUT="$(said "WAIT until later")" launch hive next --project Bee-ruche/toy --login alice --needs-accepted abc
check "next: its lines passed through, its exit code kept" eval '[ "$CODE" -eq 0 ] && [ "$OUT" = "WAIT until later" ]'
check "next: the tool's command line" grep -qx "python3 -I /hive/protocol/tools/hive/hive.py next --project Bee-ruche/toy --login alice --fork toy --needs-accepted abc --state /hive/state --needs-home /hive/home --needs-shown $HOME/.hive/needs/bee-ruche/toy" "$STUB_DIR/args.tool"
check "next: the clone, the protocol read-only, the state read-only, the needs' folder below the launcher's home" eval \
  'grep -qx "type=bind,source=$CLONE,target=/work" "$STUB_DIR/mounts.tool" && grep -qx "type=bind,source=$PROTOCOL,target=/hive/protocol,readonly" "$STUB_DIR/mounts.tool" \
   && grep -qx "type=bind,source=$HOME/.hive/state/Bee-ruche/toy,target=/hive/state,readonly" "$STUB_DIR/mounts.tool" \
   && grep -qx "type=bind,source=$HOME/.hive/needs/bee-ruche/toy,target=/hive/home/.hive/needs/bee-ruche/toy" "$STUB_DIR/mounts.tool" \
   && [ "$(wc -l < "$STUB_DIR/mounts.tool")" -eq 4 ]'
check "next: the tool runs as the clone's owner, on the network with no route out, with no credential" \
  grep -q "^run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --cpus 2 --memory 2g --network hive-inner --label hive.role=tool --user 1000:1000 .* -e HOME=/tmp/home -e LANG=C.UTF-8 -e TZ=UTC -e https_proxy=http://hive-egress:3128 -w /work " "$STUB_DIR/calls"
STUB_TOOL_OUT="$(said "REFUSED (x): y")" STUB_TOOL_CODE=1 launch hive submit --project Bee-ruche/toy --login alice --task toy-0001 --deal d
check "submit: a refusal's line and exit code passed through, the slot emptied" eval '[ "$CODE" -eq 1 ] && [ "$OUT" = "REFUSED (x): y" ] && untouched'
check "submit: the slot mounted, --hand-over given, no state, no needs" eval \
  'grep -qx "type=bind,source=$SLOT,target=/hive/outbox" "$STUB_DIR/mounts.tool" && grep -q -- "--task toy-0001 --deal d --hand-over /hive/outbox\$" "$STUB_DIR/args.tool" \
   && ! grep -q "needs\|state" "$STUB_DIR/mounts.tool"'
STUB_TOOL_OUT="$(said "STARTED hive/work/toy-0001 at $BASE")" launch hive start --project Bee-ruche/toy --login alice --task toy-0001 --deal d
check "start: STARTED kept for the sandbox" eval '[ "$CODE" -eq 0 ] && grep -qx "STARTED hive/work/toy-0001 at $BASE" "$HOME/.hive/started/Bee-ruche/toy"'
STUB_TOOL_OUT="$(said "STARTED hive/work/toy-0001 at $BASE")" STUB_TOOL_CODE=3 launch hive start --project Bee-ruche/toy --login alice --task toy-0001 --deal d
check "start: a stop forgets the last STARTED" eval '[ "$CODE" -eq 3 ] && [ ! -e "$HOME/.hive/started/Bee-ruche/toy" ]'
mkdir -p "$SLOT" && touch "$SLOT/handover.bundle"
launch "${READY[@]}"
check "refused: a slot an earlier run left full, emptied" eval 'refused 2 "the hand-over slot held what an earlier run left" && slot_empty && ! ran tool'

# ---------------------------------------------------------------------------------------------------------------
# The hand-overs: pushed when they are what the command makes, refused otherwise, the slot emptied either way.

ASK=$(ask_commit)
GOOD=$(hand_over ready hive/ready "$ASK")
case_ready "ready: the ask pushed, ASKED then the held THEN line" "$GOOD" eval \
  '[ "$CODE" -eq 0 ] && [ "$OUT" = "$(printf "ASKED %s\nTHEN: stop here." "$ASK")" ] && [ "$(fork_ref hive/ready)" = "$ASK" ] && slot_empty'
check "ready: hand-over-check run on a copy, read-only, in a container that never sees the clone" eval \
  'grep -q "^type=bind,source=$HOME/.hive/push/.copy.[A-Za-z0-9]*,target=/hive/handover,readonly\$" "$STUB_DIR/mounts.check" && ! grep -q "/work\|$CLONE" "$STUB_DIR/mounts.check" \
   && grep -qx "python3 -I /hive/protocol/tools/hive/hive.py hand-over-check --project Bee-ruche/toy --login alice --hand-over /hive/handover" "$STUB_DIR/args.check"'

bad() {  # <name> <a change of the good hand-over's folder, as shell> <the line's beginning>
  local dir
  dir=$(mktemp -d "$T/h/bad.XXXXXX")
  cp -r "$GOOD"/. "$dir"
  (cd "$dir" && eval "$2")
  WANT="$3"
  case_ready "refused: $1" "$dir" eval 'refused 2 "$WANT" && untouched'
}
bad "another action" "sed -i 's/^action ready/action duty/' handover.txt" "the hand-over is not the one local.sh hive ready writes"
bad "another branch" "sed -i 's|^branch hive/ready|branch hive/duty|' handover.txt" "the hand-over's branch is not the one"
bad "a key it does not know" "echo 'fork x' >> handover.txt" "the hand-over's file holds a key this launcher does not know"
bad "a key twice" "echo 'action ready' >> handover.txt" "the hand-over's file says action twice"
bad "a CR" "sed -i 's/\$/\r/' handover.txt" "the hand-over's file holds a byte the tool does not write"
bad "a NUL" "printf 'x\0\n' >> handover.txt" "the hand-over's file holds a byte the tool does not write"
bad "a file longer than the tool writes" "head -c 1100 /dev/zero | tr '\0' x >> handover.txt; echo >> handover.txt" "the hand-over's file is longer than the tool writes"
bad "no end to its last line" "printf %s \"\$(cat handover.txt)\" > handover.txt" "the hand-over's file does not end its last line"
bad "another version" "sed -i 's/^hive-handover 1/hive-handover 2/' handover.txt" "the hand-over's file is not of the version"
bad "an empty line" "echo >> handover.txt" "a line of the hand-over's file is not"
bad "a commit of another form" "sed -i 's/^commit .*/commit 123/' handover.txt" "the hand-over's commit is not a commit's id"
bad "a line missing" "sed -i '/^commit /d' handover.txt" "the hand-over's file does not hold the lines its action writes"
bad "a line of more" "echo 'task toy-0001' >> handover.txt" "the hand-over's task is not the one the command names"
bad "no bundle" "rm handover.bundle" "the hand-over holds no bundle"
bad "a bundle without its file" "rm handover.txt" "the tool said it handed over, and its slot holds no hand-over's file"
bad "another file in the slot" "touch extra" "the slot holds another file than the hand-over's own"
bad "the file as a link" "mv handover.txt '$T/h/real.txt' && ln -s '$T/h/real.txt' handover.txt" "the tool said it handed over, and its slot holds no hand-over's file"
bad "a bundle git does not read" "printf 'not a bundle\n' > handover.bundle" "the hand-over's bundle is not one git reads"
head -c 8000 /dev/urandom > "$T/noise"
NOISE=$(printf '100644 blob %s\tnoise\n' "$(git -C "$MAKER" hash-object -w "$T/noise")" | git -C "$MAKER" mktree)
case_ready "refused: a bundle larger than an ask's" "$(hand_over ready hive/ready "$(commit_tree "$NOISE" "$(ask_message)")")" \
  eval 'refused 2 "the hand-over'"'"'s bundle is larger than what local.sh hive ready makes" && untouched'
OTHER_ASK=$(ask_commit bob)
bad "a bundle of another commit" "sed -i 's/^commit .*/commit $OTHER_ASK/' handover.txt" "the hand-over's bundle does not hold the one branch"
case_ready "refused: an ask for another member" "$(hand_over ready hive/ready "$OTHER_ASK")" eval 'refused 2 "the hand-over'"'"'s commit is for another member" && untouched'
case_ready "refused: an ask with a parent" "$(hand_over ready hive/ready "$(commit_tree "$EMPTY_TREE" "$(ask_message)" "$BASE")")" \
  eval '{ refused 2 "the hand-over'"'"'s commit has a parent or files" || refused 2 "the hand-over'"'"'s bundle is larger"; } && untouched'
TREE=$(git -C "$MAKER" rev-parse "$BASE^{tree}")
case_ready "refused: an ask that holds files" "$(hand_over ready hive/ready "$(commit_tree "$TREE" "$(ask_message)")")" \
  eval '{ refused 2 "the hand-over'"'"'s commit has a parent or files" || refused 2 "the hand-over'"'"'s bundle is larger"; } && untouched'
case_ready "refused: an ask signed with another address" "$(EMAIL=me@example.com; hand_over ready hive/ready "$(commit_tree "$EMPTY_TREE" "$(ask_message)")")" \
  eval 'refused 2 "the hand-over'"'"'s commit is not signed with the login'"'"'s address" && untouched'
case_ready "refused: a release's commit handed over as an ask" "$(hand_over ready hive/ready "$(commit_tree "$EMPTY_TREE" "$(release_message toy-0001)")")" \
  eval 'refused 2 "the hand-over'"'"'s commit is not what local.sh hive ready makes" && untouched'
ODD=$(printf 'tree %s\nauthor alice 1 +0000\ncommitter alice 1 +0000\n\n%s' "$EMPTY_TREE" "$(ask_message)" | git -C "$MAKER" hash-object -t commit --literally -w --stdin)
case_ready "refused: an object git's checks refuse" "$(hand_over ready hive/ready "$ODD")" eval 'refused 2 "git refused the hand-over'"'"'s objects" && untouched'

reset_world
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" STUB_CHECK_OUT="$(said "REFUSED (protected_path): no")" STUB_CHECK_CODE=1 launch "${READY[@]}"
check "refused: hand-over-check's REFUSED passed through, exit 1" eval '[ "$CODE" -eq 1 ] && [ "$OUT" = "REFUSED (protected_path): no" ] && untouched'
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" STUB_CHECK_OUT="$(said "CHECKED $ASK 0 0")" launch "${READY[@]}"
check "refused: CHECKED for other bytes" eval 'refused 2 "hand-over-check did not say CHECKED for these very files" && untouched'
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" STUB_CHECK_OUT="$(said)" STUB_CHECK_CODE=3 launch "${READY[@]}"
check "refused: hand-over-check's own error, its exit code kept" eval '[ "$CODE" -eq 3 ] && untouched'
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready" "HANDED-OVER y hive/ready")" launch "${READY[@]}"
check "refused: two HANDED-OVER lines" eval 'refused 2 "the tool'"'"'s lines are not those of one hand-over" && untouched'
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" STUB_TOOL_CODE=2 launch "${READY[@]}"
check "refused: HANDED-OVER from a tool that failed" eval 'refused 2 "the tool'"'"'s lines are not those of one hand-over" && untouched'
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said)" STUB_TOOL_CODE=2 launch "${READY[@]}"
check "a tool that failed after writing its hand-over: the slot emptied" eval '[ "$CODE" -eq 2 ] && untouched'
reset_world
printf '[url "file://%s/elsewhere/"]\n\tinsteadOf = file://%s/github/alice/\n' "$T" "$T" >> "$HOME/.gitconfig"
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" launch "${READY[@]}"
check "refused: an insteadOf of this machine's settings" eval 'refused 2 "this machine'"'"'s git settings send the fork'"'"'s address elsewhere" && untouched'
reset_world
printf '[url "file://%s/elsewhere/"]\n\tpushInsteadOf = file://%s/github/alice/\n' "$T" "$T" >> "$HOME/.gitconfig"
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" launch "${READY[@]}"
check "refused: a pushInsteadOf of this machine's settings" eval 'refused 2 "this machine'"'"'s git settings send the fork'"'"'s address elsewhere" && untouched'
reset_world
mv "$HOME/.hive/state/Bee-ruche/toy" "$T/state-aside"
launch hive next --project Bee-ruche/toy --login alice
check "refused: next with no state" eval 'refused 2 "there is no state at" && ! ran tool'
mv "$T/state-aside" "$HOME/.hive/state/Bee-ruche/toy"
mv "$CLONE" "$T/clone-aside"
launch hive next --project Bee-ruche/toy --login alice
check "refused: a worker's command with no clone" eval 'refused 2 "there is no clone at" && nothing_ran'
mv "$T/clone-aside" "$CLONE"
reset_world
mv "$FORK" "$T/fork-aside"
STUB_HANDOVER="$GOOD" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" launch "${READY[@]}"
check "refused: a push that does not land" eval 'refused 2 "the push to your fork did not land" && slot_empty'
mv "$T/fork-aside" "$FORK"

# The withdrawal, a release, a duty and its release, a candidate.
reset_world
git -C "$FORK" update-ref refs/heads/hive/ready "$BASE"
STUB_HANDOVER="$(hand_over withdraw hive/ready "")" STUB_TOOL_OUT="$(said "HANDED-OVER delete hive/ready")" launch "${READY[@]}" --withdraw
check "ready --withdraw: the branch deleted, WITHDRAWN" eval '[ "$CODE" -eq 0 ] && [ "$OUT" = WITHDRAWN ] && [ -z "$(fork_ref hive/ready)" ] && slot_empty'
reset_world
git -C "$FORK" update-ref refs/heads/hive/duty "$BASE"
STUB_HANDOVER="$(hand_over withdraw hive/ready "")" STUB_TOOL_OUT="$(said "HANDED-OVER delete hive/ready")" launch hive duty --project Bee-ruche/toy --login alice --withdraw
check "refused: duty --withdraw handing over ready's deletion" eval 'refused 2 "the hand-over'"'"'s branch is not the one" && [ -n "$(fork_ref hive/duty)" ] && slot_empty'
reset_world
RELEASE=$(commit_tree "$EMPTY_TREE" "$(release_message toy-0001)")
STUB_HANDOVER="$(hand_over release hive/release/toy-0001 "$RELEASE" toy-0001)" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/release/toy-0001")" \
  launch hive release --project Bee-ruche/toy --login alice --task toy-0001 --deal d --because out_of_reach
check "release: RELEASED" eval '[ "$CODE" -eq 0 ] && [ "$OUT" = "RELEASED $RELEASE" ] && [ "$(fork_ref hive/release/toy-0001)" = "$RELEASE" ]'
reset_world
STUB_HANDOVER="$(hand_over release hive/release/toy-0002 "$RELEASE" toy-0002)" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/release/toy-0002")" \
  launch hive release --project Bee-ruche/toy --login alice --task toy-0001 --deal d --because out_of_reach
check "refused: a release of another task than the command's" eval 'refused 2 "the hand-over'"'"'s branch is not the one" && untouched'
reset_world
DUTY=$(commit_tree "$EMPTY_TREE" "$(duty_message)")
STUB_HANDOVER="$(hand_over duty hive/duty "$DUTY")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/duty")" launch hive duty --project Bee-ruche/toy --login alice
check "duty: ASKED" eval '[ "$CODE" -eq 0 ] && [ "$OUT" = "ASKED $DUTY" ] && [ "$(fork_ref hive/duty)" = "$DUTY" ]'
reset_world
STUB_HANDOVER="$(hand_over duty-release hive/duty "$DUTY")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/duty")" launch hive duty --project Bee-ruche/toy --login alice --release cannot_run
check "refused: a duty's ask handed over as its release" eval 'refused 2 "the hand-over'"'"'s commit is not what local.sh hive duty makes" && untouched'
reset_world
GIVEN=$(commit_tree "$EMPTY_TREE" "$(duty_release_message)")
STUB_HANDOVER="$(hand_over duty-release hive/duty "$GIVEN")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/duty")" launch hive duty --project Bee-ruche/toy --login alice --release cannot_run
check "duty --release: RELEASED" eval '[ "$CODE" -eq 0 ] && [ "$OUT" = "RELEASED $GIVEN" ] && [ "$(fork_ref hive/duty)" = "$GIVEN" ]'

SUBMIT=(hive submit --project Bee-ruche/toy --login alice --task toy-0001 --deal d)
case_submit() {  # <name> <hand-over folder> <condition…>
  local name="$1"
  reset_world
  STUB_HANDOVER="$2" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/submit/toy-0001" "THEN: the hive judges it.")" launch "${SUBMIT[@]}"
  shift 2
  check "$name" "$@"
}
MARKER=$(candidate toy-0001)
case_submit "submit: the candidate pushed, resting on the project's commit, PUSHED" "$(hand_over submit hive/submit/toy-0001 "$MARKER" "$BASE" main toy-0001)" eval \
  '[ "$CODE" -eq 0 ] && [ "$OUT" = "$(printf "PUSHED %s\nTHEN: the hive judges it." "$MARKER")" ] && [ "$(fork_ref hive/submit/toy-0001)" = "$MARKER" ]'
LONE=$(commit_tree "$EMPTY_TREE" "base")
case_submit "refused: a candidate resting on a commit that is not the project's" \
  "$(hand_over submit hive/submit/toy-0001 "$(commit_tree "$EMPTY_TREE" "$(submit_message toy-0001)" "$LONE")" "$LONE" main toy-0001)" \
  eval 'refused 2 "the candidate does not rest on a commit of the project'"'"'s branch" && untouched'
case_submit "refused: a project branch that is not there" "$(hand_over submit hive/submit/toy-0001 "$MARKER" "$BASE" stable toy-0001)" \
  eval 'refused 2 "the project'"'"'s branch could not be fetched" && untouched'
WORK=$(git -C "$MAKER" rev-parse "$MARKER^")
case_submit "refused: a marker on two commits" \
  "$(hand_over submit hive/submit/toy-0001 "$(commit_tree "$(git -C "$MAKER" rev-parse "$MARKER^{tree}")" "$(submit_message toy-0001)" "$WORK" "$BASE")" "$BASE" main toy-0001)" \
  eval 'refused 2 "the candidate'"'"'s marker does not rest on one commit" && untouched'
DEEP=$(commit_tree "$(git -C "$MAKER" rev-parse "$MARKER^{tree}")" "more" "$WORK")
case_submit "refused: work that does not rest on the project's commit alone" \
  "$(hand_over submit hive/submit/toy-0001 "$(commit_tree "$(git -C "$MAKER" rev-parse "$MARKER^{tree}")" "$(submit_message toy-0001)" "$DEEP")" "$BASE" main toy-0001)" \
  eval 'refused 2 "the candidate'"'"'s work does not rest on the project'"'"'s commit alone" && untouched'
case_submit "refused: a marker that changes files" \
  "$(hand_over submit hive/submit/toy-0001 "$(commit_tree "$TREE" "$(submit_message toy-0001)" "$WORK")" "$BASE" main toy-0001)" \
  eval 'refused 2 "the candidate'"'"'s marker changes files" && untouched'
case_submit "refused: a marker of another action" \
  "$(hand_over submit hive/submit/toy-0001 "$(commit_tree "$(git -C "$MAKER" rev-parse "$MARKER^{tree}")" "$(release_message toy-0001)" "$WORK")" "$BASE" main toy-0001)" \
  eval 'refused 2 "the candidate'"'"'s marker is not submit'"'"'s" && untouched'
case_submit "refused: a candidate of another member" "$(hand_over submit hive/submit/toy-0001 "$(candidate toy-0001 bob)" "$BASE" main toy-0001)" \
  eval 'refused 2 "the hand-over'"'"'s commit is for another member" && untouched'
case_submit "refused: a candidate's file without its base" "$(d=$(hand_over submit hive/submit/toy-0001 "$MARKER" "$BASE" main toy-0001); sed -i '/^base /d' "$d/handover.txt"; printf '%s' "$d")" \
  eval 'refused 2 "the hand-over'"'"'s file does not hold the lines its action writes" && untouched'

# Drawn hand-overs, pushed, with one fixed refusal at a random place among them.
DRAWN=8 FIXED=$((RANDOM % 8)) drawn_ok=1
for i in $(seq 0 $((DRAWN - 1))); do
  reset_world
  if [ "$i" -eq "$FIXED" ]; then
    STUB_HANDOVER="$(hand_over ready hive/ready "$(ask_commit bob)")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" launch "${READY[@]}"
    refused 2 "the hand-over's commit is for another member" && untouched || drawn_ok=""
    continue
  fi
  member=$(printf 'alice\nAlice\nALICE\naLiCe' | sed -n "$((RANDOM % 4 + 1))p")
  task="t$((RANDOM % 900 + 100))-$((RANDOM % 9000 + 1000))"
  if [ $((RANDOM % 2)) -eq 0 ]; then
    commit=$(commit_tree "$EMPTY_TREE" "$(ask_message "$member")")
    STUB_HANDOVER="$(hand_over ready hive/ready "$commit")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/ready")" launch "${READY[@]}"
    [ "$CODE" -eq 0 ] && [ "$(fork_ref hive/ready)" = "$commit" ] || drawn_ok=""
  else
    commit=$(candidate "$task" "$member")
    STUB_HANDOVER="$(hand_over submit "hive/submit/$task" "$commit" "$BASE" main "$task")" STUB_TOOL_OUT="$(said "HANDED-OVER x hive/submit/$task")" \
      launch hive submit --project Bee-ruche/toy --login alice --task "$task" --deal d
    [ "$CODE" -eq 0 ] && [ "$(fork_ref "hive/submit/$task")" = "$commit" ] || drawn_ok=""
  fi
done
check "drawn hand-overs pushed, the fixed refusal among them (at $FIXED) refused" test -n "$drawn_ok"

# ---------------------------------------------------------------------------------------------------------------
# The sandbox, the check, the clone, the state.

reset_world
SANDBOX=(sandbox --project Bee-ruche/toy --login alice -- make check)
launch "${SANDBOX[@]}"
check "refused: the sandbox before STARTED" eval 'refused 2 "no task is started in this clone" && nothing_ran'
mkdir -p "$HOME/.hive/started/Bee-ruche" && echo "STARTED x at y" > "$HOME/.hive/started/Bee-ruche/toy"
launch "${SANDBOX[@]}"
check "refused: a project with no sandbox's folder" eval 'refused 2 "the clone holds no folder bee" && nothing_ran'
mkdir -p "$CLONE/bee/sandbox" "$CLONE/.github" && echo "FROM x" > "$CLONE/bee/sandbox/Dockerfile" && touch "$CLONE/CLAUDE.md"
STUB_OWNER=0:0 STUB_SANDBOX_MAKES=.claude STUB_SANDBOX_CODE=4 launch "${SANDBOX[@]}"
check "sandbox: the command's exit code kept, a guarded name it made set aside" eval \
  '[ "$CODE" -eq 4 ] && [ ! -e "$CLONE/.claude" ] && ls "$CLONE" -a | grep -q "^\.claude\.created-in-sandbox\." && printf "%s\n" "$OUT" | grep -q "^LOCAL set-aside .claude .claude.created-in-sandbox."'
check "sandbox: no network, never root, the clone, its guarded names read-only, .git reduced" eval \
  'grep -q "^run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --cpus 2 --memory 2g --network none --label hive.role=sandbox --user 65534:65534 " "$STUB_DIR/calls" \
   && grep -qx "type=bind,source=$CLONE,target=/work" "$STUB_DIR/mounts.sandbox" && grep -qx "type=bind,source=$CLONE/bee,target=/work/bee,readonly" "$STUB_DIR/mounts.sandbox" \
   && grep -qx "type=bind,source=$CLONE/.github,target=/work/.github,readonly" "$STUB_DIR/mounts.sandbox" && grep -qx "type=bind,source=$CLONE/CLAUDE.md,target=/work/CLAUDE.md,readonly" "$STUB_DIR/mounts.sandbox" \
   && grep -qx "type=tmpfs,target=/work/.git" "$STUB_DIR/mounts.sandbox" && grep -qx "type=bind,source=$CLONE/.git/HEAD,target=/work/.git/HEAD,readonly" "$STUB_DIR/mounts.sandbox" \
   && ! grep -q "/hive/outbox\|/.git/config" "$STUB_DIR/mounts.sandbox" && grep -qx "make check" "$STUB_DIR/args.sandbox" && grep -qx "type=bind,source=$HOME/.hive/needs/bee-ruche/toy,target=/needs,readonly" "$STUB_DIR/mounts.sandbox"'
rm -rf "$CLONE"/.claude.created-in-sandbox.*
ln -s /etc "$CLONE/.cursor"
launch "${SANDBOX[@]}"
check "refused: a guarded name that is a link" eval 'refused 2 "the clone'"'"'s .cursor is a link" && ! ran sandbox'
rm "$CLONE/.cursor"

launch check --project Bee-ruche/toy --login alice
check "check: its lines" eval '[ "$CODE" -eq 0 ] && printf "%s\n" "$OUT" | grep -qx "NAMES-HELD 3" && printf "%s\n" "$OUT" | grep -qx "LOCAL clone $CLONE" \
  && grep -q -- "names --project Bee-ruche/toy --system linux\$" "$STUB_DIR/args.names"'
STUB_NAMES_REFUSE=1 launch check --project Bee-ruche/toy --login alice
check "refused: check, the tip's names" eval '[ "$CODE" -eq 2 ] && case "$ERR" in "hive: the project'"'"'s tip holds two names"*) true ;; *) false ;; esac'
launch clone --project Bee-ruche/toy --login alice
check "refused: clone into a folder that holds files" eval 'refused 2 "$CLONE already holds files" && ! ran clone'
mv "$CLONE" "$T/clone-aside"
launch clone --project Bee-ruche/toy --login alice
check "clone: made by the tool's container, from the fork's address" eval '[ "$CODE" -eq 0 ] && grep -qx "git -c core.hooksPath=/dev/null clone --quiet --no-recurse-submodules --template= file://$T/github/alice/toy /work" "$STUB_DIR/args.clone"'
rm -rf "$CLONE" && mv "$T/clone-aside" "$CLONE"
launch refresh --project Bee-ruche/toy
check "refresh: the state, read-write for this command alone" eval '[ "$CODE" -eq 0 ] && grep -qx "type=bind,source=$HOME/.hive/state/Bee-ruche/toy,target=/hive/state" "$STUB_DIR/mounts.refresh"'

echo "$PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ]
