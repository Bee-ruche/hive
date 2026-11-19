#!/usr/bin/env python3
"""judge.json's SHA-256 and key figures (FORMATS), as a judging step publishes them; a verdict checks the report against them.
  python3 report.py judge.json                   the figures, « key=value » lines (empty values: no report)
  python3 report.py judge.json --code CODE       the published figures: code=CODE then the figures, once the report is checked;
                                                  code=2 if it fails its check (none or malformed for code 0, another
                                                  code stated) (ruche-0117); a refusal (1) needs no report (ruche-0136)
  python3 report.py judge.json --verify S.json --base BASE --head HEAD
      S.json: the figures the judging step published, BASE and HEAD the judged commits; 0 the same report, its code 0,
      those commits and both seeds drawn by the judge (ruche-0136); 1 not; 2 error. Any non-zero exit blocks the verdict.
Standard library only: a verdict step can run this file alone (docs/common-judge.md)."""

import hashlib
import json
import os
import re
import stat
import sys

REPORT_MAX = 32 << 20  # bytes; judge.json is far smaller (judge.py caps its list of suspicious constructs)
FORMATS = {"fingerprint": r"[0-9a-f]{64}", "suspects": r"0|[1-9][0-9]{0,8}", "outputs_compared": r"0|[1-9][0-9]{0,15}",
           "plugin": r"[0-9a-f]{64}", "seed": r"[0-9a-f]{2,64}", "base": r"[0-9a-f]{40}|", "head": r"[0-9a-f]{40}|"}


ISSUES = {"0": "correct", "1": "refusal", "2": "environment_error"}  # judge.py's exit code and judge.json's judge.outcome (ruche-0136)


def judge_of(data):
    """The report's judge section (judge.json's keys and values are English, ruche-0148). ValueError if the report is not a
    mapping."""
    report = json.loads(data)
    if not isinstance(report, dict):
        raise ValueError("report without its judge section (not a mapping)")
    return report.get("judge")


class Gap(Exception):  # the report read is not the one the judging step published
    pass


def read(path):
    """The report's bytes: a regular file, never through a link, at most REPORT_MAX; None if there is none."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(REPORT_MAX + 1) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    if not 0 < len(data) <= REPORT_MAX:
        raise ValueError(f"the report is not a regular file of 1 to {REPORT_MAX} bytes")
    return data


def digits(data):
    """{output: text} of a report's bytes; ValueError if it or any figure is malformed."""
    try:
        judge = judge_of(data)
        suspects, omitted = judge["suspicious_constructs"], judge.get("suspicious_constructs_omitted", 0)
        values = {"fingerprint": hashlib.sha256(data).hexdigest(), "outputs_compared": judge["verification"]["outputs_compared"],
                  "plugin": judge["plugin"], "seed": judge["seed"], "base": judge.get("base") or "", "head": judge.get("head") or ""}
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"report without its judge section ({e!r})")
    if type(suspects) is not list or type(omitted) is not int or omitted < 0 or type(values["outputs_compared"]) is not int \
            or any(type(values[k]) is not str for k in ("plugin", "seed", "base", "head")):
        raise ValueError("malformed figure in the report")
    values = {k: str(len(suspects) + omitted if k == "suspects" else values[k]) for k in FORMATS}
    if [k for k, pattern in FORMATS.items() if not re.fullmatch(pattern, values[k])]:
        raise ValueError("malformed figure in the report")
    return values


def outcome(data):
    """The report's own code (judge.code, with its judge.outcome); ValueError unless it is one of ISSUES."""
    try:
        judge = judge_of(data)
        code, name = judge["code"], judge["outcome"]
    except (KeyError, TypeError) as e:
        raise ValueError(f"report without its code ({e!r})")
    if type(code) is not int or ISSUES.get(str(code)) != name:
        raise ValueError("malformed code in the report")
    return str(code)


def contradicts(path):
    """True if the report, read and parsed, states a code or an issue other than a refusal's."""
    try:
        judge = judge_of(read(path) or b"{}")
        code = judge.get("code", 1) if isinstance(judge, dict) else 1
        return type(code) is not int or code != 1 or isinstance(judge, dict) and judge.get("outcome", ISSUES["1"]) != ISSUES["1"]
    except (OSError, ValueError, AttributeError, RecursionError):
        return False


def publish(path, code):
    """The published figures: {"code": ..., figures}; code 2 and no figures if the report fails its check. A refusal needs no
    report: code 1 stays 1 whatever state its report is in, unless the report states another code."""
    try:
        if code == "1" and contradicts(path):
            raise ValueError("the report's code is not the judge's exit code")
        if code == "1":
            return {"code": "1", **dict.fromkeys(FORMATS, "")}
        data = read(path)
        if code not in ISSUES or (code == "0" and data is None):
            raise ValueError("no report for code 0, or a code other than 0, 1 and 2")
        if data is not None and outcome(data) != code:
            raise ValueError("the report's code is not the judge's exit code")
        return {"code": code, **(digits(data) if code == "0" else dict.fromkeys(FORMATS, ""))}
    except (OSError, ValueError) as e:
        print(f"report: error: {e}; code 2 published", file=sys.stderr)
        return {"code": "2", **dict.fromkeys(FORMATS, "")}


def verify(path, published, base, head):
    """Refuses (Gap) a report whose SHA-256 or any figure differs from the published ones, whose published code is
    not 0, or whose commits are not the judged ones (base, head); returns it."""
    if not isinstance(published, dict) or str(published.get("code")) != "0":
        raise Gap("the judging step's code is not 0")
    if not all(isinstance(c, str) and re.fullmatch(r"[0-9a-f]{40}", c) for c in (base, head)):
        raise Gap("the judged base and head are required (40 hexadecimal digits)")
    data = read(path)
    if data is None or not isinstance(published, dict) or not re.fullmatch(FORMATS["fingerprint"], str(published.get("fingerprint"))):
        raise Gap("no report, or no SHA-256 among the published figures")
    if hashlib.sha256(data).hexdigest() != published["fingerprint"]:
        raise Gap("its SHA-256 is not the one the judging step published")
    values = digits(data)
    gaps = [k for k, v in values.items() if str(published.get(k, "")) != v]
    if gaps:
        raise Gap("figure(s) other than the published ones: " + ", ".join(gaps))
    if (values["base"], values["head"]) != (base, head):
        raise Gap("base or head other than the judged ones")
    if outcome(data) != "0":
        raise Gap("the report is not a judgement's (its own code is not 0)")
    if judge_of(data).get("seed_origin") != {"seed": "drawn", "order_seed": "drawn"}:
        raise Gap("a seed given on the command line, or its origin unsaid: a local reproduction, never a judgement")
    return json.loads(data)


def main(argv):
    try:
        if len(argv) == 1:
            data = read(argv[0])
            print("\n".join(f"{k}={v}" for k, v in (digits(data) if data else dict.fromkeys(FORMATS, "")).items()))
            return 0
        if len(argv) == 3 and argv[1] == "--code":
            print("\n".join(f"{k}={v}" for k, v in publish(argv[0], argv[2]).items()))
            return 0
        if len(argv) == 7 and argv[1::2] == ["--verify", "--base", "--head"]:
            with open(argv[2], encoding="utf-8") as f:
                verify(argv[0], json.loads(f.read(1 << 20)), argv[4], argv[6])
            return 0
    except (Gap, OSError, ValueError) as e:
        print(f"report: {'REFUSAL' if isinstance(e, Gap) else 'error'}: {e}", file=sys.stderr)
        return 1 if isinstance(e, Gap) else 2
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
