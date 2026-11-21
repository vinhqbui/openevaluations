"""The Margincode arm's fixed pieces: the pinned release, the Claude Code hooks, and session validity.

No Harbor import here, so CI tests this without `--extra run`. The hooks mirror margincode-bench's
`settings()` (crates/margincode-bench/src/runner.rs) with `--jit-hooks`, the setup the E4 relay
runs used: SessionStart, PostToolUse, PreToolUse and Stop. Margincode was called Scholion until
2026-11-12; the log directory keeps that name because published runs and tools/oe/handoff.py read it.
"""

import copy
import hashlib
import json
import os
import re
import shlex
import urllib.request
import uuid
from pathlib import Path

AV_RELEASE = "release/0.0.4"
TARBALL = "margincode-v0.0.4-x86_64-unknown-linux-gnu"
SHA256_UNSET = "0" * 64
SHA256 = SHA256_UNSET  # not pinned yet: set it from the release's published {TARBALL}.tar.gz.sha256
URL = f"https://github.com/margincode-dev/open-margincode/releases/download/{AV_RELEASE}/{TARBALL}.tar.gz"
MIN_GLIBC = (2, 39)  # what the release binaries link against (built on ubuntu-latest)
BINS = ("av", "margincode", "margincode-daemon")  # `av up` looks for margincode-daemon next to av

AV_URL = "http://127.0.0.1:7420"
AGENT = "claude-code"  # margincode-bench's agent name; the task owner, so the hooks may write
LOG = "/logs/agent/scholion"  # inside /logs/agent, which Harbor copies back to <trial>/agent
AV_BIN = '"$HOME/.local/bin/av"'
PATH = 'export PATH="$HOME/.local/bin:$PATH"'
HELPER = "/installed-agent/oe_av.py"
UPLOAD = "/tmp/margincode.tar.gz"
# Set on every hook command and on Claude's own environment (its Bash tool can run `av record`).
# AV_HOOK_WAIT_SECS=0: the Stop hook would otherwise wait 600 s for backlog work that never comes.
AV_ENV = {"AV_URL": AV_URL, "AV_AGENT": AGENT, "AV_HOOK_WAIT_SECS": "0"}
HOOK_NAMES = ("session-start", "post-edit", "pre-read", "stop")


def _cmd(name, args=""):
    prefix = " ".join(f"{k}={v}" for k, v in AV_ENV.items())
    run = f"{prefix} {AV_BIN} hook {name}{args} 2>>{LOG}/hooks.err"
    if name == "session-start":
        run += f" | tee -a {LOG}/session-start.md"
    # The count is written before av runs, as margincode-bench does; `exit 0` because a failing hook
    # must not change what the agent does. Failures are judged afterwards from hooks.err.
    return f"echo {name} >> {LOG}/hook-count; {run}; exit 0"


def _hook(cmd, matcher=None):
    h = {"hooks": [{"type": "command", "command": cmd}]}
    return {"matcher": matcher, **h} if matcher else h


def hook_settings(budget=800, jit=True):
    """Claude Code settings JSON with the av hooks (passed to `claude --settings`)."""
    hooks = {
        "SessionStart": [_hook(_cmd("session-start", f" --budget {int(budget)}"))],
        "PostToolUse": [_hook(_cmd("post-edit"), "Edit|Write|MultiEdit|NotebookEdit")],
    }
    if jit:
        hooks["PreToolUse"] = [_hook(_cmd("pre-read"), "Read|Edit|MultiEdit")]
        hooks["Stop"] = [_hook(_cmd("stop"))]
    return {"hooks": hooks}


def install_command(tarball):
    """Unpack the uploaded release archive and install its binaries into ~/.local/bin."""
    bins = " ".join(f"/tmp/mc/{TARBALL}/{b}" for b in BINS)
    return (f"set -euo pipefail; mkdir -p ~/.local/bin /tmp/mc && tar -xzf {tarball} -C /tmp/mc && "
            f"install -m 0755 {bins} ~/.local/bin/ && rm -rf /tmp/mc && ~/.local/bin/av --version")


def daemon_log_copy():
    """Keep the daemon log: `av up` writes it into its home, ~/.margincode on a fresh machine."""
    return f"cp ~/.margincode/daemon.log {LOG}/ 2>/dev/null; true"


def finish_command():
    """After Claude: the final checkpoint and the records into finish.json and records.json, then the log."""
    return f"python3 {HELPER} finish --out {LOG}; {daemon_log_copy()}"


def setup_command():
    """The daemon with its bundled Postgres, and /app imported as repo `app` (as the agent user)."""
    return (f"{PATH}; mkdir -p {LOG} && : > {LOG}/hook-count && : > {LOG}/hooks.err && "
            f"av --version > {LOG}/av-version.txt && T0=$(date +%s) && "
            f"av up && av repo add app /app && echo $(( $(date +%s) - T0 )) > {LOG}/up-secs")


def task_title(instruction):
    return (instruction.strip().splitlines() or ["task"])[0][:80]


def swap_command(ws):
    """The agent and the verifier both work in /app: make it the task's jj workspace (as root)."""
    return f"mv /app /app.base && ln -s {shlex.quote(ws)} /app"


def start_command(title, start_args=""):
    """The task start (av_container.py start); the goal comes in through $OE_AV_GOAL."""
    return (f"python3 {HELPER} start --title {shlex.quote(title)} --goal-env OE_AV_GOAL "
            f"--base /app --repo app --out {LOG}{start_args}")


def merge_settings(user, ours):
    """User settings with our hooks appended per event; neither input is changed."""
    merged = copy.deepcopy(user or {})
    hooks = merged.setdefault("hooks", {})
    for event, entries in ours["hooks"].items():
        hooks.setdefault(event, []).extend(copy.deepcopy(entries))
    return merged


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _pack_part(output):
    """The SessionStart output before its first line starting with "av: ". From 0.0.4 the hook prints
    the pack's markdown and then its own lines, the first "av: before your final message, ..."
    (margincode-cli hook.rs print_pack). Output with no such line, as 0.0.2's, is all pack."""
    lines = output.splitlines(keepends=True)
    cut = next((i for i, ln in enumerate(lines) if ln.startswith("av: ")), len(lines))
    return "".join(lines[:cut])


def evaluate(log_dir):
    """Per-session av metadata, plus `oe_invalid` when the arm did not really run.

    A session is invalid when no SessionStart hook fired (no pack reached the agent), the pack was
    empty, any hook wrote an error, or the final checkpoint failed. margincode-bench only checks the
    first; the count alone is written before `av` runs, so it cannot show that av answered.
    av_pack_chars is the pack part of the SessionStart output; av_hook_chars is all of it.
    """
    d = Path(log_dir)
    counts = {}
    for line in (_read(d / "hook-count") or "").splitlines():
        if line.strip():
            counts[line.strip()] = counts.get(line.strip(), 0) + 1
    output = _read(d / "session-start.md") or ""
    pack = _pack_part(output)
    errors = [ln for ln in (_read(d / "hooks.err") or "").splitlines() if ln.strip()]
    try:
        finish = json.loads(_read(d / "finish.json") or "{}")
    except ValueError:
        finish = {}
    version = (_read(d / "av-version.txt") or "").strip() or None
    meta = {
        "av_hook_counts": counts,
        "av_pack_chars": len(pack),
        "av_hook_chars": len(output),
        "av_hook_errors": len(errors),
        "av_records": finish.get("record_count"),
        "av_checkpoint_ok": finish.get("checkpoint_ok") is True,
        "av_version": version,
    }
    for key in ("up_secs", "rss_kb", "daemon_restarted"):
        if key in finish:
            meta[f"av_{key}"] = finish[key]
    if not counts.get("session-start"):
        meta["oe_invalid"] = "the av hooks never fired"
    elif not pack.strip():
        meta["oe_invalid"] = "empty session-start pack"
    elif errors:
        meta["oe_invalid"] = f"av hook errors: {errors[0][:200]}"
    elif finish.get("checkpoint_ok") is not True:
        meta["oe_invalid"] = "final checkpoint failed"
    return meta


def glibc_ok(ldd_version_line):
    m = re.search(r"(?:GLIBC|GNU libc)\D*?(\d+)\.(\d+)", ldd_version_line) or re.search(
        r"\)\s*(\d+)\.(\d+)\s*$", ldd_version_line)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= MIN_GLIBC


def _urlretrieve(url, dest):
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


class NotPinned(RuntimeError):
    pass


def release_tarball(download=None):
    """The pinned release tarball on the host, downloaded once into $OE_CACHE and sha256-checked."""
    if SHA256 == SHA256_UNSET:
        raise NotPinned(f"no sha256 is pinned for {AV_RELEASE}: set SHA256 in agents/oe_agents/av_settings.py "
                        f"from the release's published {TARBALL}.tar.gz.sha256")
    cache = Path(os.environ.get("OE_CACHE") or Path.home() / ".cache" / "openevaluations")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{TARBALL}.tar.gz"
    if not path.exists():
        tmp = cache / f"{TARBALL}.{os.getpid()}.{uuid.uuid4().hex[:8]}.part"  # never shared with another process
        try:
            (download or _urlretrieve)(URL, tmp)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SHA256:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"{path}: sha256 {digest} is not the pinned {SHA256}")
    return path


def main(argv=None):
    """`python -m oe_agents.av_settings fetch`: download and check the pinned release once, before
    `harbor run`, so a changed release stops a CI leg with one clear error and no paid trial."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if argv != ["fetch"]:
        print("usage: python -m oe_agents.av_settings fetch", file=sys.stderr)
        return 2
    try:
        print(release_tarball())
    except NotPinned as e:
        print(f"::error::Margincode {AV_RELEASE}: {e}. Nothing was downloaded and no trial was started.",
              file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"::error::Margincode {AV_RELEASE} ({URL}) does not match the sha256 pinned in "
              f"agents/oe_agents/av_settings.py ({SHA256}). The release asset changed or the pin is "
              f"wrong; no trial was started. {e}", file=sys.stderr)
        return 1
    except OSError as e:  # URLError, HTTPError and timeouts are OSErrors
        print(f"::error::could not download Margincode {AV_RELEASE} ({URL}); no trial was started. {e}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
