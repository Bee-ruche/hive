#!/usr/bin/env bash
# The local bee's launcher: the hive's worker on Windows, macOS and Linux, through Docker.
#
# The worker's tool (hive.py) runs in a Linux container that holds no credential and reaches GitHub only, through the
# hive's gate (egress.py); the project's code runs in its own sandbox's image, with no network; the push to the
# owner's fork is made by this machine's own git, from a store of this launcher's, of what the tool handed over
# (hive.py --hand-over) once it is checked twice: here with git, then by hive.py hand-over-check in a fresh
# container that never sees the clone. The hive cannot tell the commits apart from pushed ones.
#
#   local.sh check   --project <owner/name> --login <login> [--fork <name>]
#   local.sh clone   --project <owner/name> --login <login> [--fork <name>]
#   local.sh refresh --project <owner/name>
#   local.sh hive    <setup|next|start|ready|submit|release|duty> --project … --login … [--fork …] [the tool's options]
#   local.sh sandbox --project <owner/name> --login <login> [--fork <name>] -- <command…>
#
# Lines: « LOCAL <word> <value> », the tool's own lines passed through (ASKED, PUSHED, RELEASED and WITHDRAWN come
# from here, once the push has landed, in place of the tool's HANDED-OVER), and errors as « hive: <sentence> » on
# the standard error with the tool's exit codes: 2 an error, 1 a refusal, 3 a stop.
#
# Places, all under ~/.hive and built from the arguments alone, each matched by the tool's own patterns first:
#   protocol/                      the hive's protocol, a clone the owner keeps (the guide's « The run »): hive.py from here
#   work/<login>/<fork>/           the fork's clone, made by the tool's container (clone), never by this machine's git
#   state/<owner>/<name>/          the project's state (refresh)
#   needs/<owner>/<name>/          the project's needs (lower case), shown to the tool and, read-only, to the sandbox
#   outbox/<owner>/<name>/         the one hand-over slot: never shown to the sandbox, emptied after every pushing command
#   started/<owner>/<name>         what the last « start » printed: the sandbox runs only after it
#   push/<owner>/<name>.git        this launcher's store: the only place this machine's git fetches into and pushes from
#
# Written for bash 3.2 (macOS's own) and Git Bash: no associative array, no ${x,,}, no mapfile.
set -u

# (The tests' copy, test_local.sh, replaces these lines and no other: a folder of bare repositories for GitHub, and
# the rule that lets git read such a folder.)
GITHUB="https://github.com"
FILE_PROTOCOL="never"

DOCKER="docker"
GIT="git"
CPUS=2
MEMORY=2g
INNER="hive-inner"          # the network with no route out, on which the tool's containers sit
EGRESS="hive-egress"        # the gate's container, on that network and on Docker's default bridge
EGRESS_PORT=3128
CLOCK_SKEW=60               # seconds between this machine's clock and Docker's, at most
ASK_BYTES=4096              # an ask's, a release's, a duty's bundle, at most
CANDIDATE_BYTES=268435456   # a candidate's bundle, at most (hive.py CHANGED_BYTES_MOST)
PROJECT_COMMITS=500         # how far back from the project's tip a candidate's base may lie (hive.py PROJECT_COMMITS)
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GUARDED="bee .claude .mcp.json .cursor .github AGENTS.md CLAUDE.md hive .gitignore .gitattributes"  # read-only in the sandbox
GIT_VIEW="HEAD refs packed-refs objects shallow index"  # what the sandbox sees of .git, read-only

# The tool's patterns (hive.py LOGIN, REPO_NAME, FORK_NAME, TASK_ID, REVISION).
LOGIN_RE='^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$'
NAME_RE='^[A-Za-z0-9._-]{1,100}$'
TASK_RE='^[a-z0-9]+(-[a-z0-9]+)*-[0-9]{4}$'
REVISION_RE='^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$'
SHA_RE='^[0-9a-f]{40}$'

die() { printf 'hive: %s\n' "$*" >&2; exit 2; }
say() { printf '%s\n' "$*"; }
lower() { printf '%s' "$1" | tr 'A-Z' 'a-z'; }

case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) SYSTEM=windows ;;
  Darwin) SYSTEM=macos ;;
  *) SYSTEM=linux ;;
esac
# Git Bash rewrites what looks like a path in a program's arguments: never for docker's.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

host_path() {  # a place of this machine as Docker takes it (C:/Users/… on Windows)
  if [ "$SYSTEM" = windows ]; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

same_or_below() {  # true if $1 is $2 or lies below it (without case on Windows and macOS)
  local a="$1" b="$2"
  if [ "$SYSTEM" != linux ]; then a=$(lower "$a"); b=$(lower "$b"); fi
  [ "$a" = "$b" ] || case "$a" in "$b"/*) return 0 ;; *) return 1 ;; esac
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# ---------------------------------------------------------------------------------------------------------------
# The command line: every word known, each option of the tool's own given as two words, and the launcher's own
# options (--state, --hand-over, --needs-home, --needs-shown, --upstream-url, --no-push) never the caller's.

COMMAND="${1:-}"
[ $# -gt 0 ] && shift
SUB=""
case "$COMMAND" in
  check|clone|refresh|sandbox) ;;
  hive)
    SUB="${1:-}"
    [ $# -gt 0 ] && shift
    case "$SUB" in
      setup|next|start|ready|submit|release|duty) ;;
      *) die "local.sh hive takes one of setup, next, start, ready, submit, release, duty: the worker's commands, and no other" ;;
    esac ;;
  *) die "local.sh takes check, clone, refresh, hive or sandbox" ;;
esac

# The options each command takes: « name » takes a value, « name! » is a flag.
case "$COMMAND:$SUB" in
  check:|clone:) KNOWN="project login fork" ;;
  refresh:) KNOWN="project" ;;
  sandbox:) KNOWN="project login fork" ;;
  hive:setup) KNOWN="project login fork" ;;
  hive:next) KNOWN="project login fork needs-accepted despite-needs!" ;;
  hive:start) KNOWN="project login fork task deal needs-accepted despite-needs!" ;;
  hive:ready) KNOWN="project login fork tier prefer withdraw! needs-accepted despite-needs!" ;;
  hive:submit) KNOWN="project login fork task deal message model" ;;
  hive:release) KNOWN="project login fork task deal because" ;;
  hive:duty) KNOWN="project login fork role release withdraw!" ;;
esac

PROJECT="" LOGIN="" FORK="" TASK="" WITHDRAW="" DUTY_RELEASE=""
PASS=()       # the tool's options, as given
SANDBOXED=()  # the sandbox's command, after --
while [ $# -gt 0 ]; do
  word="$1"
  shift
  if [ "$word" = "--" ] && [ "$COMMAND" = sandbox ]; then
    SANDBOXED=("$@")
    break
  fi
  case "$word" in
    --*=*) die "give each option and its value as two words ($word)" ;;
    --?*) name="${word#--}" ;;
    *) die "an option was expected, not '$word': local.sh takes no other word" ;;
  esac
  kind=""
  for known in $KNOWN; do
    if [ "$known" = "$name" ]; then kind=value; elif [ "$known" = "$name!" ]; then kind=flag; fi
  done
  [ -n "$kind" ] || die "--$name is not an option of local.sh $COMMAND${SUB:+ $SUB} (the launcher gives --state, --hand-over and the needs' places itself)"
  if [ "$kind" = flag ]; then
    PASS+=("$word")
    [ "$name" = withdraw ] && WITHDRAW=1
    continue
  fi
  [ $# -gt 0 ] || die "--$name needs a value"
  value="$1"
  shift
  case "$name" in
    project) [ -z "$PROJECT" ] || die "--project given twice"; PROJECT="$value" ;;
    login) [ -z "$LOGIN" ] || die "--login given twice"; LOGIN="$value" ;;
    fork) [ -z "$FORK" ] || die "--fork given twice"; FORK="$value" ;;
    *)
      [ "$name" = task ] && TASK="$value"
      [ "$name" = release ] && DUTY_RELEASE="$value"
      PASS+=("$word" "$value") ;;
  esac
done

[ -n "$PROJECT" ] || die "--project: the project's repository, owner/name, as the user's prompt names it"
OWNER="${PROJECT%%/*}"
NAME="${PROJECT#*/}"
if [ "$OWNER/$NAME" != "$PROJECT" ] || ! [[ $OWNER =~ $LOGIN_RE ]] || ! [[ $NAME =~ $NAME_RE ]] || [ "$NAME" = . ] || [ "$NAME" = .. ]; then
  die "--project: the project's repository on GitHub, owner/name"
fi
if [ "$COMMAND" != refresh ]; then
  [[ $LOGIN =~ $LOGIN_RE ]] || die "--login: your GitHub login"
  FORK="${FORK:-$NAME}"
  if ! [[ $FORK =~ $NAME_RE ]] || [ "$FORK" = . ] || [ "$FORK" = .. ]; then die "--fork: the name of your fork's repository"; fi
  [ "$(lower "$LOGIN/$FORK")" != "$(lower "$PROJECT")" ] || die "the fork named is the project's own repository: the worker pushes to their own fork only"
fi
if [ "$COMMAND" = sandbox ] && [ ${#SANDBOXED[@]} -eq 0 ]; then die "local.sh sandbox runs the command given after --"; fi
if [ -n "$TASK" ] && ! [[ $TASK =~ $TASK_RE ]]; then die "--task: the task's id, as the hive's lines give it"; fi

HIVE="$HOME/.hive"
PROTOCOL="$HIVE/protocol"
CLONE="$HIVE/work/$LOGIN/$FORK"
STATE="$HIVE/state/$OWNER/$NAME"
NEEDS="$HIVE/needs/$(lower "$OWNER")/$(lower "$NAME")"
SLOT="$HIVE/outbox/$OWNER/$NAME"
STARTED="$HIVE/started/$OWNER/$NAME"
STORE="$HIVE/push/$OWNER/$NAME.git"
FORK_URL="$GITHUB/$LOGIN/$FORK"
PROJECT_URL="$GITHUB/$OWNER/$NAME"

# ---------------------------------------------------------------------------------------------------------------
# This machine: where the session stands, its programs, Docker, the clock, the image.

[ -d "$PROTOCOL/.git" ] && [ -f "$PROTOCOL/tools/hive/hive.py" ] || die "the hive's protocol is not at $PROTOCOL: take it as the guide's « The run » says"
HERE=$(pwd -P)
if [ -d "$CLONE" ]; then CLONE_REAL=$(cd "$CLONE" && pwd -P); else CLONE_REAL="$CLONE"; fi
if [ "$COMMAND" != refresh ]; then
  if same_or_below "$HERE" "$CLONE_REAL" || same_or_below "$CLONE_REAL" "$HERE"; then
    die "this session's folder ($HERE) is the clone, lies inside it or above it: start the assistant in a folder of its own (~/hive-desk), and run local.sh from there"
  fi
fi
old_ifs="$IFS"; IFS=:
for entry in $PATH; do
  case "$entry" in /*) ;; *) IFS="$old_ifs"; die "the PATH holds a relative entry ($entry): this launcher runs git and docker only from places named from the root" ;; esac
  if same_or_below "$entry" "$CLONE_REAL"; then IFS="$old_ifs"; die "the PATH holds a folder of the clone ($entry): nothing of the clone is run on this machine"; fi
done
IFS="$old_ifs"
command -v "$GIT" >/dev/null 2>&1 || die "git is not on this machine's PATH: install git (Git for Windows on Windows)"
command -v "$DOCKER" >/dev/null 2>&1 || die "docker is not on this machine's PATH: install Docker (Docker Desktop on Windows and macOS) and start it"

store_git() {  # this launcher's own store, reading none of this machine's settings
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$STORE" -c core.hooksPath=/dev/null -c core.fsmonitor=false \
    -c protocol.ext.allow=never -c protocol.file.allow="$FILE_PROTOCOL" -c transfer.fsckObjects=true -c core.autocrlf=false "$@"
}

ostype=$("$DOCKER" info --format '{{.OSType}}' 2>/dev/null) || die "Docker does not answer: start Docker (Docker Desktop on Windows and macOS), then run the command again"
[ "$ostype" = linux ] || die "Docker runs $ostype containers here: switch it to Linux containers"
DOCKERFILE_ID=$(GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$PROTOCOL" rev-parse --verify --quiet "HEAD:tools/hive/Dockerfile" 2>/dev/null) \
  || die "the protocol's commit holds no tools/hive/Dockerfile: take the protocol afresh"
IMAGE="hive-tool:$DOCKERFILE_ID"
if ! "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1; then
  # Built from the protocol's commit, never from its work tree, nor pulled from a registry.
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$PROTOCOL" -c core.autocrlf=false show "HEAD:tools/hive/Dockerfile" \
    | "$DOCKER" build --quiet -t "$IMAGE" - >/dev/null 2>&1 || die "Docker could not build the tool's image: check that Docker has network, then run the command again"
fi

LIMITS=(--rm --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --cpus "$CPUS" --memory "$MEMORY")
PROTOCOL_MOUNT=(--mount "type=bind,source=$(host_path "$PROTOCOL"),target=/hive/protocol,readonly")

probe() {  # the owner of a folder as the containers see it, then Docker's clock, from a throwaway container
  "$DOCKER" run "${LIMITS[@]}" --network none --label hive.role=probe --mount "type=bind,source=$(host_path "$1"),target=/probed,readonly" \
    "$IMAGE" sh -c 'stat -c %u:%g /probed && date -u +%s'
}

OWNER_IDS=""
watch_clock_and_owner() {  # $1: the folder the tool works in
  local said
  said=$(probe "$1") || die "Docker could not run the tool's image: run the command again; if it fails again, tell the user"
  OWNER_IDS=$(printf '%s\n' "$said" | sed -n 1p)
  local docker_now now
  docker_now=$(printf '%s\n' "$said" | sed -n 2p)
  now=$(date -u +%s)
  [[ $OWNER_IDS =~ ^[0-9]+:[0-9]+$ ]] && [[ $docker_now =~ ^[0-9]+$ ]] || die "Docker's answer was not understood: run the command again"
  local skew=$((now - docker_now))
  [ "$skew" -lt 0 ] && skew=$((-skew))
  [ "$skew" -le "$CLOCK_SKEW" ] || die "Docker's clock is $skew seconds away from this machine's: restart Docker Desktop, then run the command again"
}

# ---------------------------------------------------------------------------------------------------------------
# The gate: hive-inner has no route out; hive-egress, on it and on the default bridge, tunnels to github.com:443
# alone (egress.py). Started for each command and removed at its end.

egress_down() { "$DOCKER" rm -f "$EGRESS" >/dev/null 2>&1; }

egress_up() {
  if ! "$DOCKER" network inspect "$INNER" >/dev/null 2>&1; then
    "$DOCKER" network create --internal "$INNER" >/dev/null 2>&1 || die "Docker could not make the network $INNER"
  fi
  [ "$("$DOCKER" network inspect -f '{{.Internal}}' "$INNER" 2>/dev/null)" = true ] \
    || die "the network $INNER has a route out: remove it (docker network rm $INNER) and run the command again"
  egress_down
  trap 'egress_down' EXIT
  "$DOCKER" run -d --name "$EGRESS" --label hive.role=egress --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
    --cpus 1 --memory 256m --user 65534:65534 --network bridge "${PROTOCOL_MOUNT[@]}" \
    "$IMAGE" python3 -I /hive/protocol/tools/hive/egress.py --listen 0.0.0.0 --port "$EGRESS_PORT" >/dev/null 2>&1 \
    && "$DOCKER" network connect "$INNER" "$EGRESS" >/dev/null 2>&1 || die "Docker could not start the hive's gate ($EGRESS)"
  [ -z "$("$DOCKER" port "$EGRESS" 2>/dev/null)" ] || die "the hive's gate has a port published on this machine: nothing is run through it"
  # No container on the network answers to github.com: the gate's own resolver would find it before GitHub.
  local names
  names=$("$DOCKER" network inspect -f '{{range .Containers}}{{.Name}} {{end}}' "$INNER" 2>/dev/null) || die "Docker could not list the network $INNER"
  local container aliases field
  for container in $names; do
    aliases=""
    for field in Aliases DNSNames; do  # (DNSNames: Docker 25 and later)
      aliases="$aliases $("$DOCKER" inspect -f "{{range \$k, \$v := .NetworkSettings.Networks}}{{if eq \$k \"$INNER\"}}{{join \$v.$field \" \"}}{{end}}{{end}}" "$container" 2>/dev/null)"
    done
    for alias in $container $aliases; do
      case "$(lower "${alias%.}")" in
        github.com|*.github.com) die "a container on the network $INNER answers to $alias: nothing is run there while it does (docker rm -f $container)" ;;
      esac
    done
  done
  # From the network, no name outside the machine resolves: a resolver that forwarded would be a way out.
  if "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=dns "$IMAGE" sh -c 'getent hosts github.com || getent hosts example.com' >/dev/null 2>&1; then
    die "a name outside this machine resolves from the network $INNER: Docker's resolver forwards there, and the gate would not be the only way out"
  fi
}

TOOL_ENV=(-e HOME=/tmp/home -e LANG=C.UTF-8 -e TZ=UTC -e "https_proxy=http://$EGRESS:$EGRESS_PORT")

# ---------------------------------------------------------------------------------------------------------------
# The push: what the tool handed over, checked here with git, then by hive.py hand-over-check, then pushed by this
# machine's git, one refspec, from this launcher's store.

empty_slot() { rm -rf "$SLOT" && mkdir -p "$SLOT"; }

refuse_hand_over() {  # one line, the slot emptied, nothing pushed
  empty_slot
  die "$1: nothing was pushed. Run the command again; if it stops again, tell the user"
}

WANT_ACTION="" WANT_BRANCH=""
wanted_hand_over() {  # the action and the branch, from the command line alone
  case "$SUB" in
    ready) if [ -n "$WITHDRAW" ]; then WANT_ACTION=withdraw; else WANT_ACTION=ready; fi; WANT_BRANCH=hive/ready ;;
    duty)
      if [ -n "$WITHDRAW" ]; then WANT_ACTION=withdraw; elif [ -n "$DUTY_RELEASE" ]; then WANT_ACTION=duty-release; else WANT_ACTION=duty; fi
      WANT_BRANCH=hive/duty ;;
    submit) WANT_ACTION=submit; WANT_BRANCH="hive/submit/$TASK" ;;
    release) WANT_ACTION=release; WANT_BRANCH="hive/release/$TASK" ;;
  esac
}

H_COMMIT="" H_BASE="" H_PROJECT_BRANCH="" H_TASK=""
read_hand_over() {  # handover.txt ($1): ASCII lines, each key once and of its form, the action and the branch the command's
  local file="$1" size line key value seen="" first=1
  size=$(wc -c < "$file" | tr -d ' ')
  [ "$size" -le 1024 ] || refuse_hand_over "the hand-over's file is longer than the tool writes"
  [ "$(LC_ALL=C tr -d ' -~\n' < "$file" | wc -c | tr -d ' ')" -eq 0 ] || refuse_hand_over "the hand-over's file holds a byte the tool does not write"
  [ "$(tail -c 1 "$file" | od -An -c | tr -d ' ')" = '\n' ] || refuse_hand_over "the hand-over's file does not end its last line"
  while IFS= read -r line; do
    if [ -n "$first" ]; then
      [ "$line" = "hive-handover 1" ] || refuse_hand_over "the hand-over's file is not of the version this launcher reads"
      first=""
      continue
    fi
    key="${line%% *}"
    value="${line#* }"
    [ "$key $value" = "$line" ] || refuse_hand_over "a line of the hand-over's file is not « key value »"
    case " $seen " in *" $key "*) refuse_hand_over "the hand-over's file says $key twice" ;; esac
    seen="$seen $key"
    case "$key" in
      action) [ "$value" = "$WANT_ACTION" ] || refuse_hand_over "the hand-over is not the one local.sh hive $SUB writes" ;;
      branch) [ "$value" = "$WANT_BRANCH" ] || refuse_hand_over "the hand-over's branch is not the one local.sh hive $SUB pushes to" ;;
      commit) [[ $value =~ $SHA_RE ]] || refuse_hand_over "the hand-over's commit is not a commit's id"; H_COMMIT="$value" ;;
      base) [[ $value =~ $SHA_RE ]] || refuse_hand_over "the hand-over's base is not a commit's id"; H_BASE="$value" ;;
      project-branch) [[ $value =~ $REVISION_RE ]] && [[ $value != *..* ]] || refuse_hand_over "the hand-over's project branch is not a branch's name"; H_PROJECT_BRANCH="$value" ;;
      task) [ "$value" = "$TASK" ] || refuse_hand_over "the hand-over's task is not the one the command names"; H_TASK="$value" ;;
      *) refuse_hand_over "the hand-over's file holds a key this launcher does not know ($key)" ;;
    esac
  done < "$file"
  local want
  case "$WANT_ACTION" in
    withdraw) want=" action branch" ;;
    ready|duty|duty-release) want=" action branch commit" ;;
    release) want=" action branch commit task" ;;
    submit) want=" action branch commit base project-branch task" ;;
  esac
  [ "$(printf '%s\n' $seen | sort | tr '\n' ' ')" = "$(printf '%s\n' $want | sort | tr '\n' ' ')" ] \
    || refuse_hand_over "the hand-over's file does not hold the lines its action writes"
}

commit_field() {  # the header lines of a commit of the store, by key ($2), one per line
  store_git cat-file commit "$1" 2>/dev/null | sed -n '/^$/q;p' | sed -n "s/^$2 //p"
}

check_shape() {  # the commit's skeleton, as its command makes it
  local commit="$1" parents tree message address
  parents=$(commit_field "$commit" parent)
  tree=$(commit_field "$commit" tree)
  message=$(store_git cat-file commit "$commit" 2>/dev/null | sed '1,/^$/d')
  address="<$LOGIN@users.noreply.github.com>"
  case "$WANT_ACTION" in
    submit)
      [ "$(printf '%s\n' "$parents" | grep -c .)" -eq 1 ] || refuse_hand_over "the candidate's marker does not rest on one commit"
      local work="$parents"
      if [ "$work" != "$H_BASE" ]; then
        [ "$(commit_field "$work" parent)" = "$H_BASE" ] || refuse_hand_over "the candidate's work does not rest on the project's commit alone"
        [ "$(commit_field "$work" tree)" = "$tree" ] || refuse_hand_over "the candidate's marker changes files"
      fi
      printf '%s\n' "$message" | grep -qx "Hive-Action: submit" || refuse_hand_over "the candidate's marker is not submit's" ;;
    *)
      [ -z "$parents" ] && [ "$tree" = "$EMPTY_TREE" ] || refuse_hand_over "the hand-over's commit has a parent or files"
      local action=ready
      case "$WANT_ACTION" in release|duty-release) action=release ;; duty) action=duty ;; esac
      printf '%s\n' "$message" | grep -qx "Hive-Action: $action" || refuse_hand_over "the hand-over's commit is not what local.sh hive $SUB makes"
      for who in author committer; do
        case "$(commit_field "$commit" "$who")" in
          *" $address "*) ;;
          *) refuse_hand_over "the hand-over's commit is not signed with the login's address at GitHub" ;;
        esac
      done ;;
  esac
  printf '%s\n' "$message" | grep -i -qx "Hive-Member: $LOGIN" || refuse_hand_over "the hand-over's commit is for another member"
}

COPY=""
push_hand_over() {  # after the tool printed HANDED-OVER: everything, or one line and nothing pushed
  local copy txt bundle
  copy=$(mktemp -d "$HIVE/push/.copy.XXXXXX") || refuse_hand_over "no room to copy the hand-over"
  COPY="$copy"
  trap 'rm -rf "$COPY"; egress_down' EXIT  # (the slot: emptied by each refusal, and once copied)
  [ -f "$SLOT/handover.txt" ] && [ ! -L "$SLOT/handover.txt" ] || refuse_hand_over "the tool said it handed over, and its slot holds no hand-over's file"
  cp "$SLOT/handover.txt" "$copy/handover.txt" || refuse_hand_over "the hand-over could not be copied"
  read_hand_over "$copy/handover.txt"
  if [ "$WANT_ACTION" != withdraw ]; then
    [ -f "$SLOT/handover.bundle" ] && [ ! -L "$SLOT/handover.bundle" ] || refuse_hand_over "the hand-over holds no bundle"
    cp "$SLOT/handover.bundle" "$copy/handover.bundle" || refuse_hand_over "the hand-over could not be copied"
  fi
  [ "$(ls -A "$SLOT" | sort | tr '\n' ' ')" = "$(ls -A "$copy" | sort | tr '\n' ' ')" ] || refuse_hand_over "the slot holds another file than the hand-over's own"
  empty_slot
  txt=$(sha256 "$copy/handover.txt")

  # This launcher's store, and its one remote: the fork's address as the command line names it.
  if [ ! -d "$STORE" ]; then
    mkdir -p "$(dirname "$STORE")" && GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" init --quiet --bare --template= "$STORE" >/dev/null \
      || refuse_hand_over "this launcher's store could not be made"
  fi
  store_git remote remove fork >/dev/null 2>&1
  store_git remote add fork "$FORK_URL" || refuse_hand_over "this launcher's store could not name the fork"
  # This machine's settings are read by the push: an insteadOf or a pushInsteadOf there would send it elsewhere. The
  # push goes to the address get-url --push says, whatever the fetching address is.
  [ "$("$GIT" -C "$STORE" remote get-url --push fork)" = "$FORK_URL" ] \
    || refuse_hand_over "this machine's git settings send the fork's address elsewhere (an insteadOf or a pushInsteadOf rule): remove the rule"

  local refspec checked="CHECKED delete $WANT_BRANCH $txt"
  if [ "$WANT_ACTION" = withdraw ]; then
    refspec=":refs/heads/$WANT_BRANCH"
  else
    bundle="$copy/handover.bundle"
    local size most heads
    size=$(wc -c < "$bundle" | tr -d ' ')
    most=$ASK_BYTES
    [ "$WANT_ACTION" = submit ] && most=$CANDIDATE_BYTES
    [ "$size" -le "$most" ] || refuse_hand_over "the hand-over's bundle is larger than what local.sh hive $SUB makes"
    heads=$(store_git bundle list-heads "$bundle" 2>/dev/null) || refuse_hand_over "the hand-over's bundle is not one git reads"
    [ "$heads" = "$H_COMMIT refs/heads/$WANT_BRANCH" ] || refuse_hand_over "the hand-over's bundle does not hold the one branch, at the commit, its file names"
    if [ "$WANT_ACTION" = submit ]; then
      # The base is the project's: on its branch, at most PROJECT_COMMITS back from its tip, fetched anonymously.
      store_git fetch --quiet --no-tags "$PROJECT_URL" "+refs/heads/$H_PROJECT_BRANCH:refs/project/$H_PROJECT_BRANCH" >/dev/null 2>&1 \
        || refuse_hand_over "the project's branch could not be fetched"
      store_git rev-list --max-count="$PROJECT_COMMITS" "refs/project/$H_PROJECT_BRANCH" | grep -qx "$H_BASE" \
        || refuse_hand_over "the candidate does not rest on a commit of the project's branch"
    fi
    # The bundle's pack, unpacked with git's own checks (index-pack --strict): its head first, read as lines.
    local head_bytes
    head_bytes=$(LC_ALL=C awk '{ n += length($0) + 1 } $0 == "" { print n; exit }' "$bundle")
    [[ $head_bytes =~ ^[0-9]+$ ]] || refuse_hand_over "the hand-over's bundle has no head"
    tail -c +"$((head_bytes + 1))" "$bundle" | store_git index-pack --stdin --strict --fix-thin >/dev/null 2>&1 \
      || refuse_hand_over "git refused the hand-over's objects"
    store_git update-ref "refs/handover/$WANT_BRANCH" "$H_COMMIT" || refuse_hand_over "the hand-over's commit is not in its bundle"
    check_shape "$H_COMMIT"
    refspec="+$H_COMMIT:refs/heads/$WANT_BRANCH"
    checked="CHECKED $H_COMMIT $txt $(sha256 "$bundle")"
  fi

  # hive.py hand-over-check, in a fresh container that never sees the clone: the very bytes copied here.
  local said
  said=$("$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=check --user 65534:65534 --tmpfs /tmp:rw,size=1g \
    "${TOOL_ENV[@]}" "${PROTOCOL_MOUNT[@]}" --mount "type=bind,source=$(host_path "$copy"),target=/hive/handover,readonly" \
    "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py hand-over-check --project "$PROJECT" --login "$LOGIN" --hand-over /hive/handover)
  local code=$?
  case "$said" in
    "REFUSED ("*) printf '%s\n' "$said"; exit 1 ;;
  esac
  [ "$code" -eq 0 ] && [ "$said" = "$checked" ] || { [ "$code" -eq 0 ] || exit "$code"; die "hand-over-check did not say CHECKED for these very files: nothing was pushed. Tell the user"; }

  # The push: this machine's git and its credentials, one refspec, to the fork named by the command line.
  if ! "$GIT" -C "$STORE" -c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.ext.allow=never -c protocol.file.allow="$FILE_PROTOCOL" \
      push --quiet --porcelain --no-verify --no-follow-tags --no-signed --recurse-submodules=no fork "$refspec" >/dev/null 2>&1; then
    die "the push to your fork did not land: nothing was pushed. Run the command again; if it fails again, stop and tell the user to check that this machine's git may push to the fork"
  fi
  case "$WANT_ACTION" in
    ready|duty) say "ASKED $H_COMMIT" ;;
    submit) say "PUSHED $H_COMMIT" ;;
    release|duty-release) say "RELEASED $H_COMMIT" ;;
    withdraw) say "WITHDRAWN" ;;
  esac
}

# ---------------------------------------------------------------------------------------------------------------
# The commands.

run_tool() {  # the tool in its container at /work, on the clone; extra mounts in TOOL_MOUNTS
  "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=tool --user "$OWNER_IDS" \
    --tmpfs /tmp:rw,exec,size=2g --tmpfs /tmp/home:rw,size=1m --tmpfs "/hive/home:rw,uid=${OWNER_IDS%%:*},gid=${OWNER_IDS##*:},mode=700" "${TOOL_ENV[@]}" -w /work \
    --mount "type=bind,source=$(host_path "$CLONE"),target=/work" "${PROTOCOL_MOUNT[@]}" ${TOOL_MOUNTS[@]+"${TOOL_MOUNTS[@]}"} \
    "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py "$@"
}

TOOL_MOUNTS=()

case "$COMMAND" in
  check)
    say "LOCAL system $SYSTEM"
    say "LOCAL git $("$GIT" version | sed 's/^git version //')"
    say "LOCAL docker $("$DOCKER" version --format '{{.Server.Version}}' 2>/dev/null)"
    say "LOCAL tool-image $IMAGE"
    mkdir -p "$HIVE/work" || die "no room under $HIVE"
    watch_clock_and_owner "$HIVE/work"
    egress_up
    said=$("$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=names --user 65534:65534 --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      "${PROTOCOL_MOUNT[@]}" "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py names --project "$PROJECT" --system "$SYSTEM") || exit $?
    say "$said"
    say "LOCAL clone $CLONE"
    say "LOCAL state $STATE"
    ;;
  clone)
    if [ -e "$CLONE" ] && [ -n "$(ls -A "$CLONE" 2>/dev/null)" ]; then die "$CLONE already holds files: the clone is made once, into an empty folder"; fi
    mkdir -p "$CLONE" || die "no room under $HIVE"
    watch_clock_and_owner "$CLONE"
    egress_up
    "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=clone --user "$OWNER_IDS" --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      --mount "type=bind,source=$(host_path "$CLONE"),target=/work" "$IMAGE" \
      git -c core.hooksPath=/dev/null clone --quiet --no-recurse-submodules --template= "$FORK_URL" /work >/dev/null \
      || die "the fork could not be cloned from $FORK_URL: check that the fork exists under your account, then run the command again"
    say "LOCAL clone $CLONE"
    ;;
  refresh)
    mkdir -p "$STATE" || die "no room under $HIVE"
    watch_clock_and_owner "$STATE"
    egress_up
    "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=refresh --user "$OWNER_IDS" --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      --mount "type=bind,source=$(host_path "$STATE"),target=/hive/state" "$IMAGE" sh -c '
        if [ -d /hive/state/.git ]; then
          git -C /hive/state fetch --quiet --depth 1 "$1" hive-state && git -C /hive/state reset --quiet --hard FETCH_HEAD && git -C /hive/state clean -ffdx --quiet
        else
          git clone --quiet --depth 1 --branch hive-state "$1" /hive/state
        fi' sh "$PROJECT_URL" >/dev/null || die "the project's state could not be taken from $PROJECT_URL: run the command again"
    say "LOCAL state $STATE"
    ;;
  hive)
    [ -d "$CLONE/.git" ] || die "there is no clone at $CLONE: make it with local.sh clone"
    watch_clock_and_owner "$CLONE"
    case "$SUB" in
      next|release|duty)
        [ -d "$STATE/.git" ] || die "there is no state at $STATE: take it with local.sh refresh"
        TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$STATE"),target=/hive/state,readonly")
        PASS+=(--state /hive/state) ;;
    esac
    case "$SUB" in
      next|ready|start)
        mkdir -p "$NEEDS" || die "no room under $HIVE"
        TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$NEEDS"),target=/hive/home/.hive/needs/$(lower "$OWNER")/$(lower "$NAME")")
        PASS+=(--needs-home /hive/home --needs-shown "$(host_path "$NEEDS")") ;;
    esac
    PUSHING=""
    case "$SUB" in
      ready|submit|release|duty)
        PUSHING=1
        wanted_hand_over
        mkdir -p "$SLOT" "$HIVE/push" || die "no room under $HIVE"
        if [ -n "$(ls -A "$SLOT")" ]; then empty_slot; die "the hand-over slot held what an earlier run left: it was emptied, and nothing of it was pushed. Run the command again"; fi
        TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$SLOT"),target=/hive/outbox")
        PASS+=(--hand-over /hive/outbox) ;;
    esac
    [ "$SUB" = start ] && rm -f "$STARTED"
    egress_up
    [ -n "$PUSHING" ] && trap 'empty_slot; egress_down' EXIT
    out=$(mktemp "$HIVE/.out.XXXXXX") || die "no room under $HIVE"
    run_tool "$SUB" --project "$PROJECT" --login "$LOGIN" --fork "$FORK" ${PASS[@]+"${PASS[@]}"} > "$out"
    code=$?
    handed=$(grep -c '^HANDED-OVER ' "$out")
    if [ "$handed" -eq 0 ]; then
      cat "$out"
      if [ "$SUB" = start ] && [ "$code" -eq 0 ] && line=$(grep -m1 '^STARTED ' "$out"); then
        mkdir -p "$(dirname "$STARTED")" && printf '%s\n' "$line" > "$STARTED"
      fi
      rm -f "$out"
      exit "$code"
    fi
    if [ "$handed" -ne 1 ] || [ "$code" -ne 0 ] || [ -z "$PUSHING" ]; then
      rm -f "$out"
      refuse_hand_over "the tool's lines are not those of one hand-over"
    fi
    sed '/^HANDED-OVER /,$d' "$out"
    held=$(sed -n '/^HANDED-OVER /,$p' "$out" | sed 1d)
    rm -f "$out"
    push_hand_over
    [ -n "$held" ] && printf '%s\n' "$held"
    exit 0
    ;;
  sandbox)
    [ -d "$CLONE/.git" ] || die "there is no clone at $CLONE: make it with local.sh clone"
    [ -f "$STARTED" ] || die "no task is started in this clone (local.sh hive start prints STARTED): nothing is run from the clone before"
    for part in bee bee/sandbox; do
      [ -d "$CLONE/$part" ] && [ ! -L "$CLONE/$part" ] || die "the clone holds no folder $part: the project has no sandbox's image to run"
    done
    [ -f "$CLONE/bee/sandbox/Dockerfile" ] && [ ! -L "$CLONE/bee/sandbox/Dockerfile" ] || die "the project's sandbox has no Dockerfile: it has no form for this machine"
    SANDBOX_IMAGE="hive-sandbox:$(lower "$OWNER")-$(lower "$NAME")"
    "$DOCKER" build --quiet -t "$SANDBOX_IMAGE" "$(host_path "$CLONE/bee/sandbox")" >/dev/null 2>&1 \
      || die "Docker could not build the project's sandbox's image (bee/sandbox/Dockerfile): tell the user"
    watch_clock_and_owner "$CLONE"
    user="$OWNER_IDS"
    [ "${user%%:*}" = 0 ] && user=65534:65534  # (Docker Desktop shows the machine's files as root's: the sandbox is never root)
    MOUNTS=(--mount "type=bind,source=$(host_path "$CLONE"),target=/work")
    absent=""
    for name in $GUARDED; do
      [ -L "$CLONE/$name" ] && die "the clone's $name is a link: Docker would show what it leads to; nothing is run from this clone. Tell the user"
      if [ -e "$CLONE/$name" ]; then
        MOUNTS+=(--mount "type=bind,source=$(host_path "$CLONE/$name"),target=/work/$name,readonly")
      else
        absent="$absent $name"
      fi
    done
    MOUNTS+=(--mount "type=tmpfs,target=/work/.git")
    for name in $GIT_VIEW; do
      [ -e "$CLONE/.git/$name" ] && MOUNTS+=(--mount "type=bind,source=$(host_path "$CLONE/.git/$name"),target=/work/.git/$name,readonly")
    done
    [ -d "$NEEDS" ] && MOUNTS+=(--mount "type=bind,source=$(host_path "$NEEDS"),target=/needs,readonly")
    "$DOCKER" run "${LIMITS[@]}" --network none --label hive.role=sandbox --user "$user" -e HOME=/tmp/home -e LANG=C.UTF-8 \
      --tmpfs /tmp:rw,exec,mode=1777 -w /work "${MOUNTS[@]}" "$SANDBOX_IMAGE" "${SANDBOXED[@]}"
    code=$?
    # A guarded name the command made, where there was none, is set aside, as the project's sans-docker.sh does.
    for name in $absent; do
      if [ -e "$CLONE/$name" ] || [ -L "$CLONE/$name" ]; then
        aside="$name.created-in-sandbox.$$$RANDOM"
        mv "$CLONE/$name" "$CLONE/$aside" && say "LOCAL set-aside $name $aside"
      fi
    done
    exit "$code"
    ;;
esac
