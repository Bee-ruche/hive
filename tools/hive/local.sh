#!/usr/bin/env bash
# The local bee's launcher: the hive's worker on Windows, macOS and Linux, through Docker.
#
# The worker's tool (hive.py) runs in a Linux container that holds no credential and reaches GitHub only, through the
# hive's gate (egress.py); the project's code runs in its own sandbox's image, with no network; the push to the
# owner's fork is made by this machine's own git, from a store of this launcher's, of what the tool handed over
# (hive.py --hand-over) once it is checked twice: by hive.py hand-over-check in a fresh container that never sees the
# clone, then here with git. The hive cannot tell the commits apart from pushed ones.
#
#   local.sh login   <login>             (the user, once, typed in a real terminal of their own, never by an
#                                         assistant: the GitHub account this machine works for. On Windows, in Git
#                                         Bash: started through local.ps1, bash may not see a terminal)
#   local.sh check   --project <owner/name> --login <login> [--fork <name>]
#   local.sh clone   --project <owner/name> --login <login> [--fork <name>]
#   local.sh refresh --project <owner/name>
#   local.sh needs   --project <owner/name>             (what the project needs of a worker's machine, after the yes)
#   local.sh accept-needs --project <owner/name> <digest>  (the user, typed in a real terminal of their own, never by an
#                                         assistant: the project's needs they accept, as local.sh needs gave their digest)
#   local.sh hive    <setup|next|start|ready|submit|release|duty> --project … --login … [--fork …] [the tool's options]
#   local.sh sandbox --project <owner/name> --login <login> [--fork <name>] -- <command…>
#
# Lines: « LOCAL <word> <value> », the tool's own lines passed through (ASKED, PUSHED, RELEASED and WITHDRAWN come
# from here, once the push has landed, in place of the tool's HANDED-OVER), and errors as « hive: <sentence> » on
# the standard error with the tool's exit codes: 2 an error, 1 a refusal, 3 a stop.
#
# Places, all under ~/.hive and built from the arguments alone, each matched by the tool's own patterns first, and
# each shown to Docker by the very place it resolves to, which must be the place it names (placed: no link on the way):
#   login                          the login the user recorded (local.sh login): every command's --login must be it
#   accepted/<owner>/<name>        the digest of the project's needs the user accepted (local.sh accept-needs): the needs'
#                                  fetch runs for that digest alone
#   protocol/                      the hive's protocol, a clone the owner keeps (the guide's « The run »): hive.py from here
#   work/<login>/<fork>/           the fork's clone, made by the tool's container (clone), never by this machine's git
#   state/<owner>/<name>/          the project's state (refresh)
#   needs/<owner>/<name>/          the project's needs (lower case), fetched by the needs' own container (needs-fetch),
#                                  shown to the tool and, read-only, to the sandbox
#   outbox/<owner>/<name>/         the one hand-over slot: never shown to the sandbox, emptied after every pushing command
#   started/<owner>/<name>         what the last « start » printed: the sandbox runs only after it
#   push/<owner>/<name>.git        this launcher's store: the only place this machine's git fetches into and pushes from
#   locks/<owner>/<name>           one run at a time for a project
#
# The project's sandbox image is built from the project's commit « start » printed, its bee/sandbox taken from the
# project into this launcher's store, never from the clone. It is built with the network, as its own Dockerfile says
# (every pilot's installs packages): that file is one of the project's protected ones.
#
# Written for bash 3.2 (macOS's own) and Git Bash: no associative array, no ${x,,}, no mapfile.
set -u

# (The tests' copy, test_local.sh, replaces these lines and no other: a folder of bare repositories for GitHub, the rule
# that lets git read such a folder, and a shorter bound for the needs' fetch.)
GITHUB="https://github.com"
FILE_PROTOCOL="never"
NEEDS_SECONDS=1860         # how long the needs' fetch may take, at most (hive.py's own bound for all of them, and a minute)

DOCKER="docker"
GIT="git"
CPUS=2
MEMORY=2g
GIT_MEMORY_KB=4194304       # what this machine's git may take when it unpacks a hand-over (ulimit -v, where the system honours it)
GIT_SECONDS=600             # how long this machine's git may take to fetch or to unpack, at most
INNER="hive-inner"          # the network with no route out, on which the tool's containers sit
EGRESS_PORT=3128
CLOCK_SKEW=60               # seconds between this machine's clock and Docker's, at most
ASK_BYTES=4096              # an ask's, a release's, a duty's bundle, at most
CANDIDATE_BYTES=268435456   # a candidate's bundle, at most (hive.py CHANGED_BYTES_MOST)
PROJECT_COMMITS=500         # how far back from the project's tip a candidate's base may lie (hive.py PROJECT_COMMITS)
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# Read-only in the sandbox: what is run or obeyed on the host (the sandbox's own folder, the CI's, coding tools' and
# agents' settings and instructions, an editor's tasks, direnv's file) and the hive's files.
GUARDED="bee .claude .mcp.json .cursor .cursorrules .github AGENTS.md CLAUDE.md CLAUDE.local.md GEMINI.md .gemini .codex .windsurf \
.windsurfrules .clinerules .roo .continue .aider.conf.yml .aiderignore .vscode .idea .devcontainer .envrc hive .gitignore .gitattributes"
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
# Git Bash rewrites what looks like a path in a program's arguments: never, for docker's and git's. Every place given
# to either is given in the form it takes (host_path).
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

# The environment: no variable of git's (a GIT_DIR, a GIT_CONFIG_*, a GIT_SSH_COMMAND would change what git reads or
# where it pushes), and only this machine's own Docker daemon.
SET_ASIDE=""  # those of them that may matter to the push's sign-in, said if the push fails
for variable in $(compgen -e); do
  case "$variable" in
    GIT_ASKPASS|GIT_SSH|GIT_SSH_COMMAND|GIT_TERMINAL_PROMPT|GIT_CREDENTIAL_*) SET_ASIDE="$SET_ASIDE $variable"; unset "$variable" ;;
    GIT_*) unset "$variable" ;;
  esac
done
[ -z "${DOCKER_CONTEXT:-}" ] || die "DOCKER_CONTEXT is set: the launcher talks to this machine's Docker as its own settings name it. Unset DOCKER_CONTEXT, then run the command again"
[ -z "${DOCKER_CONFIG:-}" ] || die "DOCKER_CONFIG is set: the launcher reads Docker's settings from their usual place. Unset DOCKER_CONFIG, then run the command again"
case "${DOCKER_HOST:-}" in
  ""|unix://*|npipe://*) ;;
  *) die "DOCKER_HOST names a daemon that is not this machine's own (only unix:// and npipe:// are taken): unset it, then run the command again" ;;
esac

host_path() {  # a place of this machine as Docker and git take it (C:/Users/… on Windows)
  if [ "$SYSTEM" = windows ]; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

same_place() {  # true if the two places are one (without case on Windows and macOS)
  if [ "$SYSTEM" != linux ]; then [ "$(lower "$1")" = "$(lower "$2")" ]; else [ "$1" = "$2" ]; fi
}

same_or_below() {  # true if $1 is $2 or lies below it (without case on Windows and macOS); both resolved
  local a="$1" b="$2"
  if [ "$SYSTEM" != linux ]; then a=$(lower "$a"); b=$(lower "$b"); fi
  [ "$a" = "$b" ] || case "$a" in "$b"/*) return 0 ;; *) return 1 ;; esac
}

sha256() {  # of a file, or of the standard input with no file
  if command -v sha256sum >/dev/null 2>&1; then sha256sum ${1:+"$1"} | cut -d' ' -f1; else shasum -a 256 ${1:+"$1"} | cut -d' ' -f1; fi
}

within() {  # <seconds> <input file> <command…>: the command, its memory bounded where the system allows, killed past its time
  local seconds="$1" input="$2" pid dog code
  shift 2
  ( [ -z "$GIT_MEMORY_KB" ] || ulimit -v "$GIT_MEMORY_KB" 2>/dev/null; exec "$@" ) < "$input" &
  pid=$!
  # The watchdog holds none of the command's outputs (a reader of them would wait for it), and takes its sleep away with
  # it when it is stopped: its trap is set before the sleep starts, so a stop that comes at once leaves no sleep behind.
  ( sleeping=""; trap '[ -z "$sleeping" ] || kill "$sleeping" 2>/dev/null; exit 0' TERM
    sleep "$seconds" & sleeping=$!; wait "$sleeping"; kill "$pid" 2>/dev/null ) < /dev/null > /dev/null 2>&1 &
  dog=$!
  wait "$pid"
  code=$?
  kill "$dog" 2>/dev/null
  wait "$dog" 2>/dev/null
  return "$code"
}

# ---------------------------------------------------------------------------------------------------------------
# The command line: every word known, each option of the tool's own given as two words, and the launcher's own
# options (--state, --hand-over, --needs-home, --needs-shown, --upstream-url, --no-push) never the caller's.

HIVE="$HOME/.hive"
COMMAND="${1:-}"
[ $# -gt 0 ] && shift

if [ "$COMMAND" = login ]; then
  # The user's own step, once: an existing record is never replaced by this command (the user removes the file).
  [ $# -eq 1 ] && [[ $1 =~ $LOGIN_RE ]] || die "local.sh login takes one word: the user's GitHub login"
  # (In a terminal of the user's own: an assistant runs its commands with no terminal. This guards against an
  # assistant's error, not against one that would pretend to be a terminal.)
  [ -t 0 ] && [ -t 1 ] || die "local.sh login is the user's own step, typed in a terminal of their own (on Windows, in Git Bash, which bash sees as a terminal where PowerShell's console may not be): an assistant never runs it"
  mkdir -p "$HIVE" || die "no room under $HIVE"
  if [ -f "$HIVE/login" ]; then
    [ "$(lower "$(cat "$HIVE/login")")" = "$(lower "$1")" ] \
      || die "this machine works for $(printf %q "$(cat "$HIVE/login")") already: to work for another account, the user removes $HIVE/login by hand"
  else
    printf '%s\n' "$1" > "$HIVE/login" || die "no room under $HIVE"
  fi
  say "LOCAL login $(cat "$HIVE/login")"
  exit 0
fi

if [ "$COMMAND" = accept-needs ]; then
  # The user's own step, for each project and each version of its needs: the digest local.sh needs gave, accepted by the
  # user in a terminal of their own (as login), so that an assistant misled by a project's text never opens the needs'
  # fetch, the one container that reaches hosts other than GitHub, without them. It replaces the project's record.
  [ $# -eq 3 ] && [ "$1" = --project ] || die "local.sh accept-needs takes --project <owner/name> and the digest local.sh needs gave"
  owner="${2%%/*}" name="${2#*/}"
  if [ "$owner/$name" != "$2" ] || ! [[ $owner =~ $LOGIN_RE ]] || ! [[ $name =~ $NAME_RE ]] || [ "$name" = . ] || [ "$name" = .. ]; then
    die "--project: the project's repository on GitHub, owner/name"
  fi
  [[ $3 =~ ^[0-9a-f]{64}$ ]] || die "local.sh accept-needs takes the digest of the project's needs, 64 hexadecimal digits, as local.sh needs printed it"
  [ -t 0 ] && [ -t 1 ] || die "local.sh accept-needs is the user's own step, typed in a terminal of their own (on Windows, in Git Bash): an assistant never runs it"
  place="$HIVE/accepted/$(lower "$owner")"
  mkdir -p "$place" && printf '%s\n' "$3" > "$place/$(lower "$name")" || die "no room under $HIVE"
  say "LOCAL accepted $(lower "$owner")/$(lower "$name") $3"
  exit 0
fi

SUB=""
case "$COMMAND" in
  check|clone|refresh|needs|sandbox) ;;
  hive)
    SUB="${1:-}"
    [ $# -gt 0 ] && shift
    case "$SUB" in
      setup|next|start|ready|submit|release|duty) ;;
      *) die "local.sh hive takes one of setup, next, start, ready, submit, release, duty: the worker's commands, and no other" ;;
    esac ;;
  *) die "local.sh takes login, accept-needs, check, clone, refresh, needs, hive or sandbox" ;;
esac

# The options each command takes: « name » takes a value, « name! » is a flag.
case "$COMMAND:$SUB" in
  check:|clone:) KNOWN="project login fork" ;;
  refresh:|needs:) KNOWN="project" ;;
  sandbox:) KNOWN="project login fork" ;;
  hive:setup) KNOWN="project login fork" ;;
  hive:next) KNOWN="project login fork needs-accepted despite-needs!" ;;
  hive:start) KNOWN="project login fork task deal needs-accepted despite-needs!" ;;
  hive:ready) KNOWN="project login fork tier prefer withdraw! needs-accepted despite-needs!" ;;
  hive:submit) KNOWN="project login fork task deal message model" ;;
  hive:release) KNOWN="project login fork task deal because" ;;
  hive:duty) KNOWN="project login fork role release withdraw!" ;;
esac

PROJECT="" LOGIN="" FORK="" TASK="" WITHDRAW="" DUTY_RELEASE="" NEEDS_ACCEPTED=""
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
      [ "$name" = needs-accepted ] && NEEDS_ACCEPTED="$value"
      PASS+=("$word" "$value") ;;
  esac
done

[ -n "$PROJECT" ] || die "--project: the project's repository, owner/name, as the user's prompt names it"
OWNER="${PROJECT%%/*}"
NAME="${PROJECT#*/}"
if [ "$OWNER/$NAME" != "$PROJECT" ] || ! [[ $OWNER =~ $LOGIN_RE ]] || ! [[ $NAME =~ $NAME_RE ]] || [ "$NAME" = . ] || [ "$NAME" = .. ]; then
  die "--project: the project's repository on GitHub, owner/name"
fi
if [ "$COMMAND" != refresh ] && [ "$COMMAND" != needs ]; then
  [[ $LOGIN =~ $LOGIN_RE ]] || die "--login: your GitHub login"
  # The login is the user's, recorded once by the user (local.sh login): a fork of any other account is never written.
  [ -f "$HIVE/login" ] || die "no login is recorded on this machine: stop, and tell the user. The user (never an assistant) types « local.sh login <their GitHub login> » once, in a terminal of their own"
  [ "$(lower "$(cat "$HIVE/login")")" = "$(lower "$LOGIN")" ] \
    || die "--login is not the login the user recorded on this machine ($(printf %q "$(cat "$HIVE/login")")): this machine works for that account alone"
  FORK="${FORK:-$NAME}"
  if ! [[ $FORK =~ $NAME_RE ]] || [ "$FORK" = . ] || [ "$FORK" = .. ]; then die "--fork: the name of your fork's repository"; fi
  [ "$(lower "$LOGIN/$FORK")" != "$(lower "$PROJECT")" ] || die "the fork named is the project's own repository: the worker pushes to their own fork only"
fi
if [ "$COMMAND" = sandbox ] && [ ${#SANDBOXED[@]} -eq 0 ]; then die "local.sh sandbox runs the command given after --"; fi
if [ -n "$TASK" ] && ! [[ $TASK =~ $TASK_RE ]]; then die "--task: the task's id, as the hive's lines give it"; fi
if [ -n "$NEEDS_ACCEPTED" ] && ! [[ $NEEDS_ACCEPTED =~ ^[0-9a-f]{64}$ ]]; then die "--needs-accepted: the digest of the project's needs the user accepted, as local.sh needs printed it"; fi

PROTOCOL="$HIVE/protocol"
CLONE="$HIVE/work/$LOGIN/$FORK"
STATE="$HIVE/state/$OWNER/$NAME"
NEEDS="$HIVE/needs/$(lower "$OWNER")/$(lower "$NAME")"
SLOT="$HIVE/outbox/$OWNER/$NAME"
STARTED="$HIVE/started/$OWNER/$NAME"
STORE="$HIVE/push/$OWNER/$NAME.git"
LOCK="$HIVE/locks/$OWNER/$NAME"
FORK_URL="$GITHUB/$LOGIN/$FORK"
PROJECT_URL="$GITHUB/$OWNER/$NAME"
EGRESS="hive-egress-$$-$RANDOM"  # the gate's container, this run's own

# ---------------------------------------------------------------------------------------------------------------
# Leaving: whatever happened, this run's gate removed, the slot emptied after a pushing command, the copy of a
# hand-over removed, the project's lock given back.

GATE_UP="" EMPTY_ON_EXIT="" COPY="" LOCKED="" FETCHER="" SAID=""
empty_slot() { rm -rf "$SLOT" && mkdir -p "$SLOT"; }
leave() {
  [ -z "$COPY" ] || rm -rf "$COPY"
  [ -z "$EMPTY_ON_EXIT" ] || empty_slot
  [ -z "$GATE_UP" ] || "$DOCKER" rm -f "$EGRESS" >/dev/null 2>&1
  [ -z "$FETCHER" ] || "$DOCKER" rm -f "$FETCHER" >/dev/null 2>&1
  [ -z "$SAID" ] || rm -f "$SAID"
  [ -z "$LOCKED" ] || rm -rf "$LOCK"
}
trap leave EXIT

# ---------------------------------------------------------------------------------------------------------------
# This machine: its places, where the session stands, its programs, Docker, the clock, the image.

mkdir -p "$HIVE" || die "no room under $HIVE"
HIVE_REAL=$(cd -P "$HIVE" && pwd -P) || die "$HIVE cannot be read"

placed() {  # <place> <the place it must resolve to> <what it is>: prints the place resolved (no link on the way, nor at its end)
  local place="$1" real
  [ -L "$place" ] && die "$3 ($place) is a link: nothing is shown to a container through a link"
  if [ -d "$place" ]; then
    real=$(cd -P "$place" && pwd -P) || die "$3 ($place) cannot be read"
  else
    real="$(cd -P "$(dirname "$place")" 2>/dev/null && pwd -P)/$(basename "$place")" || die "$3 ($place) cannot be read"
  fi
  same_place "$real" "$2" || die "$3 ($place) does not lie where it is named (a link on the way leads elsewhere): nothing is shown to a container from it"
  printf '%s' "$real"
}
below_hive() { placed "$1" "$HIVE_REAL${1#"$HIVE"}" "$2"; }

needs_own() {  # the needs' folder and the two above it: the user's own, written by no group nor others (the tool makes them 0755)
  # (docs/hosting.md, item 7: another account of this machine that could write there could change what /needs shows.
  # On Windows, Git Bash's stat shows owners and modes it makes up: nothing to read there.)
  [ "$SYSTEM" = windows ] && return 0
  local place said
  for place in "$NEEDS" "$(dirname "$NEEDS")" "$(dirname "$(dirname "$NEEDS")")"; do
    if [ "$SYSTEM" = macos ]; then said=$(stat -f '%u %Lp' "$place" 2>/dev/null); else said=$(stat -c '%u %a' "$place" 2>/dev/null); fi
    [ "${said%% *}" = "$(id -u)" ] && [ $((0${said##* } & 022)) -eq 0 ] \
      || die "$place is not your own, or a group or others may write to it: the project's needs are not shown from it (the tool makes these folders 0755)"
  done
}

[ -d "$PROTOCOL/.git" ] && [ -f "$PROTOCOL/tools/hive/hive.py" ] || die "the hive's protocol is not at $PROTOCOL: take it as the guide's « The run » says"
PROTOCOL_TOOLS=$(below_hive "$PROTOCOL/tools/hive" "the protocol's tools") || exit 2
HERE=$(pwd -P)
if [ -d "$CLONE" ]; then CLONE_REAL=$(cd -P "$CLONE" && pwd -P); else CLONE_REAL="$CLONE"; fi
if [ "$COMMAND" != refresh ] && [ "$COMMAND" != needs ]; then
  if same_or_below "$HERE" "$CLONE_REAL" || same_or_below "$CLONE_REAL" "$HERE"; then
    die "this session's folder ($HERE) is the clone, lies inside it or above it: start the assistant in a folder of its own (~/hive-desk), and run local.sh from there"
  fi
fi
set -f
old_ifs="$IFS"
IFS=: read -r -a PATH_ENTRIES <<< "$PATH"
IFS="$old_ifs"
set +f
for entry in ${PATH_ENTRIES[@]+"${PATH_ENTRIES[@]}"}; do
  case "$entry" in /*) ;; *) die "the PATH holds a relative entry ('$entry'): this launcher runs git and docker only from places named from the root" ;; esac
  [ -d "$entry" ] || continue
  resolved=$(cd -P "$entry" 2>/dev/null && pwd -P) || continue
  if same_or_below "$resolved" "$CLONE_REAL"; then die "the PATH holds a folder of the clone ($entry): nothing of the clone is run on this machine"; fi
done
command -v "$GIT" >/dev/null 2>&1 || die "git is not on this machine's PATH: install git (Git for Windows on Windows)"
command -v "$DOCKER" >/dev/null 2>&1 || die "docker is not on this machine's PATH: install Docker (Docker Desktop on Windows and macOS) and start it"

# One run at a time for a project: two would share its slot. The lock is a folder that holds its run's process id
# from the moment it exists: made aside with its pid, then renamed into place (a rename over no folder is one step;
# over one, the folder moves inside it, which says the lock is taken). A lock whose run has ended is taken over.
mkdir -p "$HIVE/locks/$OWNER" || die "no room under $HIVE"
take_lock() {
  local aside
  aside=$(mktemp -d "$HIVE/locks/$OWNER/.$NAME.XXXXXX") || return 1
  printf '%s\n' "$$" > "$aside/pid"
  mv "$aside" "$LOCK" 2>/dev/null
  if [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && [ ! -e "$LOCK/$(basename "$aside")" ]; then return 0; fi
  rm -rf "$LOCK/$(basename "$aside")" "$aside"
  return 1
}
if ! take_lock; then
  holder=$(cat "$LOCK/pid" 2>/dev/null)
  if [[ $holder =~ ^[0-9]+$ ]] && kill -0 "$holder" 2>/dev/null; then
    die "another run of local.sh is going on this project (process $holder): wait for it to end, then run the command again"
  fi
  rm -rf "$LOCK"
  take_lock || die "the project's lock ($LOCK) cannot be taken: run the command again"
fi
LOCKED=1

store_git() {  # this launcher's own store, reading none of this machine's settings
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$(host_path "$STORE")" -c core.hooksPath=/dev/null -c core.fsmonitor=false \
    -c protocol.ext.allow=never -c protocol.file.allow="$FILE_PROTOCOL" -c transfer.fsckObjects=true -c core.autocrlf=false "$@"
}
store_git_within() {  # <input file> <git's words…>: the same, bounded (within)
  local input="$1"
  shift
  within "$GIT_SECONDS" "$input" env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$(host_path "$STORE")" -c core.hooksPath=/dev/null \
    -c core.fsmonitor=false -c protocol.ext.allow=never -c protocol.file.allow="$FILE_PROTOCOL" -c transfer.fsckObjects=true -c core.autocrlf=false "$@"
}

ostype=$("$DOCKER" info --format '{{.OSType}}' 2>/dev/null) || die "Docker does not answer: start Docker (Docker Desktop on Windows and macOS), then run the command again"
[ "$ostype" = linux ] || die "Docker runs $ostype containers here: switch it to Linux containers"
# The daemon the current context of Docker's settings names: this machine's own, as DOCKER_HOST must be. (An older
# docker with no contexts answers nothing: DOCKER_HOST alone names its daemon then.)
endpoint=$("$DOCKER" context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)
case "$endpoint" in
  ""|unix://*|npipe://*) ;;
  *) die "Docker's current context names a daemon that is not this machine's own (only unix:// and npipe:// are taken): switch to this machine's own context (docker context use default), then run the command again" ;;
esac
DOCKERFILE_ID=$(GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$(host_path "$PROTOCOL")" rev-parse --verify --quiet "HEAD:tools/hive/Dockerfile" 2>/dev/null) \
  || die "the protocol's commit holds no tools/hive/Dockerfile: take the protocol afresh"
IMAGE="hive-tool:$DOCKERFILE_ID"
if ! "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1; then
  # Built from the protocol's commit, never from its work tree, nor pulled from a registry.
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" -C "$(host_path "$PROTOCOL")" -c core.autocrlf=false show "HEAD:tools/hive/Dockerfile" \
    | "$DOCKER" build --quiet -t "$IMAGE" - >/dev/null 2>&1 || die "Docker could not build the tool's image: check that Docker has network, then run the command again"
fi

# Every container runs under an init (--init): what a project's command or the tool leaves behind is reaped as it
# ends, and never fills the processes' bound (--pids-limit) of a long check.
LIMITS=(--rm --init --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --cpus "$CPUS" --memory "$MEMORY")
# The protocol's tools alone (not its .git, whose settings may hold an address with a token), read-only.
PROTOCOL_MOUNT=(--mount "type=bind,source=$(host_path "$PROTOCOL_TOOLS"),target=/hive/protocol/tools/hive,readonly")

probe() {  # the owner of a folder (resolved) as the containers see it, then Docker's clock, from a throwaway container
  "$DOCKER" run "${LIMITS[@]}" --network none --label hive.role=probe --mount "type=bind,source=$(host_path "$1"),target=/probed,readonly" \
    "$IMAGE" sh -c 'stat -c %u:%g /probed && date -u +%s'
}

OWNER_IDS=""
watch_clock_and_owner() {  # $1: the folder the tool works in, resolved
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
# The gate: hive-inner has no route out; this run's gate, on it and on the default bridge, tunnels to github.com:443
# alone (egress.py). Started for each command, waited for, and removed at its end.

egress_up() {
  if ! "$DOCKER" network inspect "$INNER" >/dev/null 2>&1; then
    "$DOCKER" network create --internal "$INNER" >/dev/null 2>&1 || die "Docker could not make the network $INNER"
  fi
  [ "$("$DOCKER" network inspect -f '{{.Internal}}' "$INNER" 2>/dev/null)" = true ] \
    || die "the network $INNER has a route out: remove it (docker network rm $INNER) and run the command again"
  GATE_UP=1
  "$DOCKER" run -d --init --name "$EGRESS" --label hive.role=egress --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
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
  # The gate listens before anything is sent through it.
  local tries=0
  until "$DOCKER" exec "$EGRESS" python3 -I -c "import socket; socket.create_connection(('127.0.0.1', $EGRESS_PORT), 2)" >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 20 ] || die "the hive's gate does not answer: run the command again; if it fails again, tell the user"
    sleep 0.5
  done
}

TOOL_ENV=(-e HOME=/tmp/home -e LANG=C.UTF-8 -e TZ=UTC -e "https_proxy=http://$EGRESS:$EGRESS_PORT")

# ---------------------------------------------------------------------------------------------------------------
# The push: what the tool handed over, checked by hive.py hand-over-check, then here with git (its objects only once
# the checker has held them to the project's bounds), then pushed by this machine's git, one refspec, from this
# launcher's store.

refuse_hand_over() {  # one line, nothing pushed (the slot is emptied as the command leaves: EMPTY_ON_EXIT)
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

ensure_store() {  # this launcher's bare store, made once with no template (no hooks), and lying where it is named
  if [ ! -d "$STORE" ]; then
    mkdir -p "$(dirname "$STORE")" && GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null "$GIT" init --quiet --bare --template= "$(host_path "$STORE")" >/dev/null \
      || die "this launcher's store could not be made"
  fi
  below_hive "$STORE" "this launcher's store" >/dev/null || exit 2
}

shares_history() {  # the fork and the project have a commit in common: asked once for each fork's address, before its first push
  # (Both are read anonymously, as the hive reads them: a project and its forks are public repositories.)
  [ "$(cat "$STORE/hive-fork" 2>/dev/null)" = "$FORK_URL" ] && return 0
  store_git_within /dev/null fetch --quiet --no-tags "$PROJECT_URL" "+HEAD:refs/shared/project" >/dev/null 2>&1 \
    && store_git_within /dev/null fetch --quiet --no-tags "$FORK_URL" "+HEAD:refs/shared/fork" >/dev/null 2>&1 \
    || refuse_hand_over "the fork or the project could not be fetched to see that the fork is the project's"
  store_git merge-base refs/shared/project refs/shared/fork >/dev/null 2>&1 \
    || refuse_hand_over "the fork $LOGIN/$FORK holds nothing of the project's history: the worker pushes to a fork of the project only"
  printf '%s\n' "$FORK_URL" > "$STORE/hive-fork"
}

push_hand_over() {  # after the tool printed HANDED-OVER: everything, or one line and nothing pushed
  local copy txt bundle_sum
  copy=$(mktemp -d "$HIVE/push/.copy.XXXXXX") || refuse_hand_over "no room to copy the hand-over"
  COPY="$copy"
  [ -f "$SLOT/handover.txt" ] && [ ! -L "$SLOT/handover.txt" ] || refuse_hand_over "the tool said it handed over, and its slot holds no hand-over's file"
  cp "$SLOT/handover.txt" "$copy/handover.txt" || refuse_hand_over "the hand-over could not be copied"
  if [ "$WANT_ACTION" != withdraw ]; then
    [ -f "$SLOT/handover.bundle" ] && [ ! -L "$SLOT/handover.bundle" ] || refuse_hand_over "the hand-over holds no bundle"
    cp "$SLOT/handover.bundle" "$copy/handover.bundle" || refuse_hand_over "the hand-over could not be copied"
  fi
  [ "$(ls -A "$SLOT" | sort | tr '\n' ' ')" = "$(ls -A "$copy" | sort | tr '\n' ' ')" ] || refuse_hand_over "the slot holds another file than the hand-over's own"
  empty_slot
  txt=$(sha256 "$copy/handover.txt")
  read_hand_over "$copy/handover.txt"
  local bundle="$copy/handover.bundle" checked="CHECKED delete $WANT_BRANCH $txt"
  if [ "$WANT_ACTION" != withdraw ]; then
    local size most heads
    size=$(wc -c < "$bundle" | tr -d ' ')
    most=$ASK_BYTES
    [ "$WANT_ACTION" = submit ] && most=$CANDIDATE_BYTES
    [ "$size" -le "$most" ] || refuse_hand_over "the hand-over's bundle is larger than what local.sh hive $SUB makes"
    bundle_sum=$(sha256 "$bundle")
    checked="CHECKED $H_COMMIT $txt $bundle_sum"
  fi

  # This launcher's store, and its one remote: the fork's address as the command line names it.
  ensure_store
  store_git remote remove fork >/dev/null 2>&1
  store_git remote add fork "$FORK_URL" || refuse_hand_over "this launcher's store could not name the fork"
  # This machine's settings are read by the push: an insteadOf or a pushInsteadOf there would send it elsewhere. The
  # push goes to the address get-url --push says, whatever the fetching address is.
  [ "$("$GIT" -C "$(host_path "$STORE")" remote get-url --push fork)" = "$FORK_URL" ] \
    || refuse_hand_over "this machine's git settings send the fork's address elsewhere (an insteadOf or a pushInsteadOf rule): remove the rule"
  if [ "$WANT_ACTION" != withdraw ]; then
    heads=$(store_git_within /dev/null bundle list-heads "$(host_path "$bundle")" 2>/dev/null) || refuse_hand_over "the hand-over's bundle is not one git reads"
    [ "$heads" = "$H_COMMIT refs/heads/$WANT_BRANCH" ] || refuse_hand_over "the hand-over's bundle does not hold the one branch, at the commit, its file names"
  fi

  # hive.py hand-over-check first, in a fresh container that never sees the clone: the very bytes copied here, held to
  # the project's bounds (pack_bounds) before this machine's git unpacks anything of them.
  local said
  said=$("$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=check --user 65534:65534 --tmpfs /tmp:rw,size=1g \
    "${TOOL_ENV[@]}" "${PROTOCOL_MOUNT[@]}" --mount "type=bind,source=$(host_path "$copy"),target=/hive/handover,readonly" \
    "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py hand-over-check --project "$PROJECT" --login "$LOGIN" --hand-over /hive/handover)
  local code=$?
  case "$said" in
    "REFUSED ("*) printf '%s\n' "$said"; exit 1 ;;
  esac
  [ "$code" -eq 0 ] || exit "$code"
  [ "$said" = "$checked" ] || die "hand-over-check did not say CHECKED for these very files: nothing was pushed. Tell the user"
  [ "$(sha256 "$copy/handover.txt")" = "$txt" ] || refuse_hand_over "the hand-over's file changed while it was checked"

  shares_history
  local refspec
  if [ "$WANT_ACTION" = withdraw ]; then
    refspec=":refs/heads/$WANT_BRANCH"
  else
    if [ "$WANT_ACTION" = submit ]; then
      # The base is the project's: on its branch, at most PROJECT_COMMITS back from its tip, fetched anonymously.
      store_git_within /dev/null fetch --quiet --no-tags "$PROJECT_URL" "+refs/heads/$H_PROJECT_BRANCH:refs/project/$H_PROJECT_BRANCH" >/dev/null 2>&1 \
        || refuse_hand_over "the project's branch could not be fetched"
      store_git rev-list --max-count="$PROJECT_COMMITS" "refs/project/$H_PROJECT_BRANCH" | grep -qx "$H_BASE" \
        || refuse_hand_over "the candidate does not rest on a commit of the project's branch"
    fi
    # The bundle's pack, unpacked with git's own checks (index-pack --strict), bounded in time and memory: taken
    # from the bytes hashed as they are read, which must be the bytes hand-over-check said CHECKED for.
    local head_bytes
    head_bytes=$(LC_ALL=C awk '{ n += length($0) + 1 } $0 == "" { print n; exit }' "$bundle")
    [[ $head_bytes =~ ^[0-9]+$ ]] || refuse_hand_over "the hand-over's bundle has no head"
    mkfifo "$copy/stream" || refuse_hand_over "no room to read the hand-over"
    sha256 < "$copy/stream" > "$copy/stream.sum" &
    local summing=$!
    tee "$copy/stream" < "$bundle" | tail -c +"$((head_bytes + 1))" > "$copy/pack"
    wait "$summing"
    [ "$(cat "$copy/stream.sum")" = "$bundle_sum" ] || refuse_hand_over "the hand-over's bundle changed while it was checked"
    store_git_within "$copy/pack" index-pack --stdin --strict --fix-thin >/dev/null 2>&1 || refuse_hand_over "git refused the hand-over's objects"
    store_git update-ref "refs/handover/$WANT_BRANCH" "$H_COMMIT" || refuse_hand_over "the hand-over's commit is not in its bundle"
    check_shape "$H_COMMIT"
    refspec="+$H_COMMIT:refs/heads/$WANT_BRANCH"
  fi

  # The push: this machine's git and its credentials, one refspec, to the fork named by the command line.
  # Bounded in time (a first sign-in in the credential manager's window included), never asking on a terminal, and not
  # bounded in memory: a credential manager (.NET's, on Windows) may reserve more address space than git does.
  if ! GIT_MEMORY_KB="" within "$GIT_SECONDS" /dev/null env GIT_TERMINAL_PROMPT=0 "$GIT" -C "$(host_path "$STORE")" -c core.hooksPath=/dev/null \
      -c core.fsmonitor=false -c protocol.ext.allow=never -c protocol.file.allow="$FILE_PROTOCOL" \
      push --quiet --porcelain --no-verify --no-follow-tags --no-signed --recurse-submodules=no fork "$refspec" >/dev/null 2>&1; then
    die "the push to your fork did not land: nothing was pushed. Run the command again; if it fails again, stop and tell the user to check that this machine's git may push to the fork${SET_ASIDE:+ (this launcher set aside$SET_ASIDE, which git's sign-in may need: the push signs in with git's own credential helper alone)}"
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

TOOL_MOUNTS=()
run_tool() {  # the tool in its container at /work, on the clone; extra mounts in TOOL_MOUNTS
  "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=tool --user "$OWNER_IDS" \
    --tmpfs /tmp:rw,exec,size=2g --tmpfs /tmp/home:rw,size=1m --tmpfs "/hive/home:rw,uid=${OWNER_IDS%%:*},gid=${OWNER_IDS##*:},mode=700" "${TOOL_ENV[@]}" -w /work \
    --mount "type=bind,source=$(host_path "$CLONE_SOURCE"),target=/work" "${PROTOCOL_MOUNT[@]}" ${TOOL_MOUNTS[@]+"${TOOL_MOUNTS[@]}"} \
    "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py "$@"
}

# Each place a container is shown is resolved and held to the place it names (placed) in the lines right before the
# docker run that mounts it, after anything long (the gate, a build, the probe). What remains: a swap made between
# those lines and Docker's mount, by something running at that very moment.

case "$COMMAND" in
  check)
    say "LOCAL system $SYSTEM"
    say "LOCAL git $("$GIT" version | sed 's/^git version //')"
    say "LOCAL docker $("$DOCKER" version --format '{{.Server.Version}}' 2>/dev/null)"
    say "LOCAL tool-image $IMAGE"
    mkdir -p "$HIVE/work" || die "no room under $HIVE"
    egress_up
    WORK=$(below_hive "$HIVE/work" "the clones' folder") || exit 2
    watch_clock_and_owner "$WORK"
    said=$("$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=names --user 65534:65534 --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      "${PROTOCOL_MOUNT[@]}" "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py names --project "$PROJECT" --system "$SYSTEM") || exit $?
    say "$said"
    say "LOCAL clone $CLONE"
    say "LOCAL state $STATE"
    ;;
  clone)
    if [ -e "$CLONE" ] && [ -n "$(ls -A "$CLONE" 2>/dev/null)" ]; then die "$CLONE already holds files: the clone is made once, into an empty folder"; fi
    mkdir -p "$CLONE" || die "no room under $HIVE"
    egress_up
    watch_clock_and_owner "$CLONE"  # (with no network, reading an owner and a clock: the places are checked after it)
    CLONE_SOURCE=$(below_hive "$CLONE" "the clone's folder") || exit 2
    "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=clone --user "$OWNER_IDS" --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      --mount "type=bind,source=$(host_path "$CLONE_SOURCE"),target=/work" "$IMAGE" \
      git -c core.hooksPath=/dev/null clone --quiet --no-recurse-submodules --template= "$FORK_URL" /work >/dev/null \
      || die "the fork could not be cloned from $FORK_URL: check that the fork exists under your account, then run the command again"
    say "LOCAL clone $CLONE"
    ;;
  needs)
    # What the project needs of a worker's machine, read by the tool in its container, through the gate: the
    # settings with git (--by-fetch), for raw.githubusercontent.com does not pass the gate. Nothing of the user's.
    egress_up
    "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=needs --user 65534:65534 --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" -w /tmp \
      "${PROTOCOL_MOUNT[@]}" "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py needs --project "$PROJECT" --by-fetch
    exit $?
    ;;
  refresh)
    mkdir -p "$STATE" || die "no room under $HIVE"
    egress_up
    watch_clock_and_owner "$STATE"  # (with no network, reading an owner and a clock: the places are checked after it)
    STATE_SOURCE=$(below_hive "$STATE" "the state's folder") || exit 2
    "$DOCKER" run "${LIMITS[@]}" --network "$INNER" --label hive.role=refresh --user "$OWNER_IDS" --tmpfs /tmp:rw,size=1g "${TOOL_ENV[@]}" \
      --mount "type=bind,source=$(host_path "$STATE_SOURCE"),target=/hive/state" "$IMAGE" sh -c '
        if [ -d /hive/state/.git ]; then
          git -C /hive/state fetch --quiet --depth 1 "$1" hive-state && git -C /hive/state reset --quiet --hard FETCH_HEAD && git -C /hive/state clean -ffdx --quiet
        else
          git clone --quiet --depth 1 --branch hive-state "$1" /hive/state
        fi' sh "$PROJECT_URL" >/dev/null || die "the project's state could not be taken from $PROJECT_URL: run the command again"
    say "LOCAL state $STATE"
    ;;
  hive)
    [ -d "$CLONE/.git" ] || die "there is no clone at $CLONE: make it with local.sh clone"
    case "$SUB" in
      next|release|duty)
        [ -d "$STATE/.git" ] || die "there is no state at $STATE: take it with local.sh refresh"
        PASS+=(--state /hive/state) ;;
    esac
    case "$SUB" in
      next|ready|start)
        (umask 022 && mkdir -p "$NEEDS") || die "no room under $HIVE"
        PASS+=(--needs-home /hive/home --needs-shown "$(host_path "$NEEDS")") ;;
    esac
    PUSHING=""
    case "$SUB" in
      ready|submit|release|duty)
        PUSHING=1
        wanted_hand_over
        mkdir -p "$SLOT" "$HIVE/push" || die "no room under $HIVE"
        if [ -n "$(ls -A "$SLOT")" ]; then empty_slot; die "the hand-over slot held what an earlier run left: it was emptied, and nothing of it was pushed. Run the command again"; fi
        PASS+=(--hand-over /hive/outbox) ;;
    esac
    [ "$SUB" = start ] && rm -f "$STARTED"
    egress_up
    [ -n "$PUSHING" ] && EMPTY_ON_EXIT=1
    watch_clock_and_owner "$CLONE"  # (with no network, reading an owner and a clock: the places are checked after it)
    ACCEPTED_RECORD="$HIVE/accepted/$(lower "$OWNER")/$(lower "$NAME")"
    if [ -n "$NEEDS_ACCEPTED" ] && [ "$SUB" = next ] && ! { [ -f "$ACCEPTED_RECORD" ] && [ ! -L "$ACCEPTED_RECORD" ] && [ "$(head -c 100 "$ACCEPTED_RECORD")" = "$NEEDS_ACCEPTED" ]; }; then
      say "LOCAL needs not-accepted-here: no files are fetched for this digest until the user, never an assistant, types « local.sh accept-needs --project $PROJECT $NEEDS_ACCEPTED » in a terminal of their own"
    elif [ -n "$NEEDS_ACCEPTED" ] && [ "$SUB" = next ]; then
      # The project's files and documents, fetched by the tool's own code (needs-fetch: https, each file held to its
      # size and SHA-256) in a container of their own: Docker's default network, which reaches the needs' hosts (the
      # gate passes github.com alone, and the fetch reads no proxy), and nothing but the protocol's tools and the
      # needs' folder: no clone, no fork, no state, no slot, no credential. For next alone, the guide's first command
      # of a run: ready and start then find the files held, and no fetch holds up a deal's clock. Its lines are said
      # as the launcher's own (LOCAL needs …), and the tool runs whatever they say: it reads the folder again, and its
      # own lines say what the project lacks (with a deal held, the deal is shown and given back as the guide says).
      # A fetch that says nothing and fails is said too (LOCAL needs fetch-failed <code>). The container has a name of
      # this run's own, removed as the launcher leaves, whatever happened.
      NEEDS_SOURCE=$(below_hive "$NEEDS" "the needs' folder") || exit 2
      needs_own
      FETCHER="hive-needs-$$-$RANDOM"
      said_file=$(mktemp "$HIVE/.needs.XXXXXX") || die "no room under $HIVE"
      SAID="$said_file"
      GIT_MEMORY_KB="" within "$NEEDS_SECONDS" /dev/null "$DOCKER" run "${LIMITS[@]}" --name "$FETCHER" --network bridge --label hive.role=needs-fetch --user "$OWNER_IDS" --tmpfs /tmp:rw,size=1g \
        --tmpfs "/hive/home:rw,uid=${OWNER_IDS%%:*},gid=${OWNER_IDS##*:},mode=700" -e HOME=/tmp -e LANG=C.UTF-8 -e TZ=UTC -w /tmp "${PROTOCOL_MOUNT[@]}" \
        --mount "type=bind,source=$(host_path "$NEEDS_SOURCE"),target=/hive/home/.hive/needs/$(lower "$OWNER")/$(lower "$NAME")" \
        "$IMAGE" python3 -I /hive/protocol/tools/hive/hive.py needs-fetch --project "$PROJECT" --needs-accepted "$NEEDS_ACCEPTED" \
        --needs-home /hive/home > "$said_file" 2>&1
      fetch_code=$?
      [ "$fetch_code" -eq 0 ] || "$DOCKER" rm -f "$FETCHER" >/dev/null 2>&1  # (past its bound, the client is killed: the container too)
      # Its lines, 4000 bytes at most, with no character of control but the line's end.
      head -c 4000 "$said_file" | tr -d '\000-\011\013-\037\177' | while IFS= read -r line; do [ -z "$line" ] || say "LOCAL needs $line"; done
      if [ "$fetch_code" -ne 0 ] && ! grep -q '^NEEDS-\(FETCHED\|MISSING\|UNACCEPTED\) ' "$said_file"; then say "LOCAL needs fetch-failed $fetch_code"; fi
      rm -f "$said_file"; SAID=""
    fi
    # Right before the tool runs: each place resolved, each mount built.
    CLONE_SOURCE=$(below_hive "$CLONE" "the clone's folder") || exit 2
    case "$SUB" in
      next|release|duty)
        STATE_SOURCE=$(below_hive "$STATE" "the state's folder") || exit 2
        TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$STATE_SOURCE"),target=/hive/state,readonly") ;;
    esac
    case "$SUB" in
      next|ready|start)
        NEEDS_SOURCE=$(below_hive "$NEEDS" "the needs' folder") || exit 2
        needs_own
        TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$NEEDS_SOURCE"),target=/hive/home/.hive/needs/$(lower "$OWNER")/$(lower "$NAME")") ;;
    esac
    if [ -n "$PUSHING" ]; then
      SLOT_SOURCE=$(below_hive "$SLOT" "the hand-over's slot") || exit 2
      TOOL_MOUNTS+=(--mount "type=bind,source=$(host_path "$SLOT_SOURCE"),target=/hive/outbox")
    fi
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
    # The image is built from the bytes « start » proved, the project's commit it printed, taken from the project
    # into this launcher's own store, never from the clone, where the assistant writes.
    TIP=$(sed -n 's/^STARTED [^ ]* at \([0-9a-f]\{40\}\)$/\1/p' "$STARTED")
    [[ $TIP =~ $SHA_RE ]] || die "the record of the last start is not one this launcher writes: run local.sh hive start again"
    ensure_store
    store_git_within /dev/null fetch --quiet --no-tags "$PROJECT_URL" "$TIP" >/dev/null 2>&1 && store_git cat-file -e "$TIP^{commit}" 2>/dev/null \
      || die "the project's commit the last start was on could not be fetched from $PROJECT_URL: run the command again"
    CONTEXT_DIR=$(mktemp -d "$HIVE/push/.context.XXXXXX") || die "no room under $HIVE"
    COPY="$CONTEXT_DIR"
    store_git_within /dev/null archive --format=tar "$TIP" bee/sandbox 2>/dev/null | tar -x -C "$CONTEXT_DIR" 2>/dev/null
    [ -f "$CONTEXT_DIR/bee/sandbox/Dockerfile" ] || die "the project's commit holds no bee/sandbox/Dockerfile: it has no sandbox's image for this machine"
    SANDBOX_IMAGE="hive-sandbox:$(lower "$OWNER")-$(lower "$NAME")"
    "$DOCKER" build --quiet -t "$SANDBOX_IMAGE" "$(host_path "$CONTEXT_DIR/bee/sandbox")" >/dev/null 2>&1 \
      || die "Docker could not build the project's sandbox's image (bee/sandbox/Dockerfile): tell the user"
    watch_clock_and_owner "$CLONE"  # (with no network, reading an owner and a clock: the places are checked after it)
    user="$OWNER_IDS"
    [ "${user%%:*}" = 0 ] && user=65534:65534  # (Docker Desktop shows the machine's files as root's: the sandbox is never root)
    # Right before the run: every place shown to the sandbox is the very place it names below the clone, resolved: a
    # link (a .git, a .git/refs, a guarded name made into one) would have Docker show what it leads to on this machine.
    CLONE_SOURCE=$(below_hive "$CLONE" "the clone's folder") || exit 2
    in_clone() { placed "$CLONE_SOURCE/$1" "$CLONE_SOURCE/$1" "the clone's $1"; }
    in_clone .git >/dev/null || exit 2
    MOUNTS=(--mount "type=bind,source=$(host_path "$CLONE_SOURCE"),target=/work")
    absent=""
    for name in $GUARDED; do
      if [ -e "$CLONE/$name" ] || [ -L "$CLONE/$name" ]; then
        source=$(in_clone "$name") || exit 2
        MOUNTS+=(--mount "type=bind,source=$(host_path "$source"),target=/work/$name,readonly")
      else
        absent="$absent $name"
      fi
    done
    MOUNTS+=(--mount "type=tmpfs,target=/work/.git")
    for name in $GIT_VIEW; do
      if [ -e "$CLONE/.git/$name" ] || [ -L "$CLONE/.git/$name" ]; then
        source=$(in_clone ".git/$name") || exit 2
        MOUNTS+=(--mount "type=bind,source=$(host_path "$source"),target=/work/.git/$name,readonly")
      fi
    done
    if [ -d "$NEEDS" ]; then
      NEEDS_SOURCE=$(below_hive "$NEEDS" "the needs' folder") || exit 2
      needs_own
      MOUNTS+=(--mount "type=bind,source=$(host_path "$NEEDS_SOURCE"),target=/needs,readonly")
    fi
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
