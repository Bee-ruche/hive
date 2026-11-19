"""Bee's common judge: errors, log and safe reading of the outputs the container wrote.

Everything the container produced is hostile: a file can be a symbolic link to a file of the
host, a named pipe that blocks reading, a huge file, or a text that holds GitHub workflow
commands. Nothing in this module follows a link, opens a special file or reads beyond a
bounded size. A project's plugin sees the outputs only through `Outputs`.
"""

import hashlib
import os
import re
import stat
import sys

OUTPUT_FILE_MAX = 256 * 1024 * 1024


class JudgeError(Exception):
    """The environment is not suitable (Docker missing, a base that does not compile, a badly set-up judge): code 2."""


class MachineFailure(JudgeError):
    """A failure of the machine that judges (Docker, its runtime, an image): an environment error, never a refusal (ruche-0136)."""


class Refusal(Exception):
    """The judge refuses variant B: code 1."""


def log(message):
    print(f"judge: {message}", file=sys.stderr, flush=True)


def clean(data, maximum=1500):
    """Text from the container, safe to show: truncated, control characters removed."""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    text = re.sub("[^\x20-\x7e\n\xa0-퟿-￿]", "?", text[-maximum:])  # nor a lone surrogate
    return text.replace("::", ": :")  # no GitHub workflow command


def read_output(root, relative, maximum=OUTPUT_FILE_MAX):
    """Reads root/relative without ever following a symbolic link (the container wrote in root).

    Returns None if the file does not exist; Refusal if it is not a regular file or if it exceeds maximum (OUTPUT_FILE_MAX at most)."""
    maximum, parts = min(maximum, OUTPUT_FILE_MAX), relative.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise Refusal(f"invalid output path: {relative}")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for p in parts[:-1]:
            try:
                deeper = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError:
                raise Refusal(f"invalid output (trapped folder): {relative}")
            os.close(fd)
            fd = deeper
        try:
            ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise Refusal(f"invalid output (link or special file): {relative}")
    finally:
        os.close(fd)
    try:
        st = os.fstat(ffd)
        if not stat.S_ISREG(st.st_mode):
            raise Refusal(f"invalid output (not a regular file): {relative}")
        if st.st_size > maximum:
            raise Refusal(f"output too large: {relative} ({st.st_size} bytes)")
        blocks, total = [], 0
        while True:
            block = os.read(ffd, 1 << 20)
            if not block:
                break
            total += len(block)
            if total > maximum:
                raise Refusal(f"output too large: {relative}")
            blocks.append(block)
        return b"".join(blocks)
    finally:
        os.close(ffd)


def require(root, relative, maximum=OUTPUT_FILE_MAX):
    data = read_output(root, relative, maximum)
    if data is None:
        raise Refusal(f"output missing: {relative}")
    return data


def status(root, relative, text=None):
    """Status file « CODE INTEGER\\n » written by a harness (return code, length produced)."""
    text = require(root, relative, 64) if text is None else text
    m = re.fullmatch(rb"(-?\d{1,6}) (\d{1,12})\n", text)
    if not m:
        raise Refusal(f"unreadable status: {relative}")
    return int(m.group(1)), int(m.group(2))


def _unreadable(error):
    raise Refusal(f"unreadable outputs: {clean(str(error), 300)}")


def freeze(root):
    """Fingerprint of an outputs folder, taken as soon as the container that wrote it ends (ruche-0036): {relative path:
    SHA-256 of a regular file, « folder », or « other » (link, special file)}. Its keys are the folder's listing;
    no link is followed, each file is read by read_output (bounded size), an unreadable folder is a refusal."""
    try:
        return _freeze(root)
    except OSError as e:  # status, listing or opening of what the container left: a refusal (1), never an error (2)
        _unreadable(e)


def _freeze(root):
    fingerprint = {}
    for folder, folders, files in os.walk(root, onerror=_unreadable):
        for name in folders + files:
            relative = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
            mode = os.lstat(os.path.join(folder, name)).st_mode
            fingerprint[relative] = (hashlib.sha256(require(root, relative)).hexdigest() if stat.S_ISREG(mode)
                                     else "folder" if stat.S_ISDIR(mode) else "other")
    return fingerprint


def copy_out(source, target):
    """The outputs a container left on its own tmpfs, copied into target (an empty folder of the judge) before that tmpfs goes
    (ruche-0117): no link followed, each file read by read_output (size bounded), a link or special file left as a link (freeze:
    « other », a refusal when read); anything unreadable is a refusal, as in freeze."""
    try:
        for folder, folders, files in os.walk(source, onerror=_unreadable):
            for name in folders + files:
                relative = os.path.relpath(os.path.join(folder, name), source)
                mode, copy = os.lstat(os.path.join(source, relative)).st_mode, os.path.join(target, relative)
                if stat.S_ISDIR(mode):
                    os.mkdir(copy)
                elif stat.S_ISREG(mode):
                    with open(copy, "xb") as f:
                        f.write(require(source, relative.replace(os.sep, "/")))
                else:
                    os.symlink("other", copy)
    except OSError as e:
        _unreadable(e)


class Outputs:
    """The outputs of a variant (A or B) for a step, one folder per side (« f », « z »…).

    It is the only view a project's plugin has of what the container wrote. It keeps what
    the plugin actually read (`read_paths`): the common judge then checks that each input had at
    least one output of B read, so that a plugin that forgets an input or a scenario is stopped
    instead of letting through an output nobody looked at (adversarial review of 28 October).

    `names` ({(side, the plugin's name): written name}): the inputs were written under other names (ruche-0037); the
    plugin keeps its own, translated here in the path's last component (« c/k000.6 » reads « c/e0012.6 »).

    With `frozen` ({side: freeze's fingerprint}, always passed by the judge), only what was frozen is read: a file
    changed, added or removed after its fingerprint is a refusal (ruche-0036)."""

    def __init__(self, roots, names=None, frozen=None):
        if isinstance(roots, Outputs):  # a new view of the same frozen outputs: its reads count separately
            roots, names, frozen = roots._roots, roots._names if names is None else names, roots.frozen
        self._roots, self._names, self.frozen = dict(roots), dict(names or {}), frozen
        self.read_paths = set()

    def __iter__(self):  # its folders (judge.erase)
        return iter(self._roots.values())

    def _path(self, side, relative):
        head, bar, last = relative.rpartition("/")
        for i in [len(last)] + [j for j in range(len(last) - 1, 0, -1) if last[j] == "."]:
            if (side, last[:i]) in self._names:
                return head + bar + self._names[(side, last[:i])] + last[i:]
        return relative

    def _root(self, side):
        if side not in self._roots:
            raise JudgeError(f"unknown side: {side}")
        return self._roots[side]

    def read(self, side, relative, maximum=OUTPUT_FILE_MAX):
        data = self.written(side, self._path(side, relative), maximum)
        if data is not None:
            self.read_paths.add((side, relative))
        return data

    def require(self, side, relative, maximum=OUTPUT_FILE_MAX):
        data = self.read(side, relative, maximum)
        if data is None:
            raise Refusal(f"output missing: {relative}")
        return data

    def status(self, side, relative):
        return status(None, relative, self.require(side, relative, 64))

    def written(self, side, path, maximum=OUTPUT_FILE_MAX):
        """The output written under this path (no translation of names), as it was frozen."""
        data = read_output(self._root(side), path, maximum)
        fingerprint = None if data is None else hashlib.sha256(data).hexdigest()
        if self.frozen is not None and fingerprint != self.frozen[side].get(path):
            raise Refusal(f"output changed, added or removed after its fingerprint: {clean(path, 200)}")
        return data

    def check_unchanged(self):
        """After the comparison: each folder is still exactly what was frozen (listing and contents)."""
        for side, root in self._roots.items():
            if freeze(root) != self.frozen[side]:
                raise Refusal(f"outputs changed, added or removed after their fingerprint (side {side})")

    def covers(self, side, name):
        """True if an output read on this side bears the input's name (« c/k000.6 » covers k000)."""
        for s, relative in self.read_paths:
            last = relative.rsplit("/", 1)[-1]
            if s == side and (last == name or last.startswith(name + ".")):
                return True
        return False
