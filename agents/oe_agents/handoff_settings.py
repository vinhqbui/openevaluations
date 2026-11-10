"""Predecessor A of the handoff benchmark: its instruction and the freeze step. No Harbor import.

A is the Scholion arm (ClaudeCodeAv), so one run leaves all four channels: the working tree, its
trajectory (Harbor writes it), its NOTES.md and its Scholion records (av_container.py finish). It
is cut by Claude Code's own `--max-turns`, the turn count pre-registered in
docs/PREREG-handoff-interrupt.md, and the tree is tarred whatever state it was cut in.
"""

FREEZE_DIR = "/logs/agent/freeze"  # inside /logs/agent, which Harbor copies back to <trial>/agent
EXCLUDES = (".git", ".jj", ".av-task", "__pycache__", ".pytest_cache")

NOTES_RULE = """\
Keep a file NOTES.md at the repository root as you go: what you found, what you tried and \
ruled out, and what you would do next. You may be stopped at any point, and another engineer \
will continue from your working tree and these notes. Update it after each step that taught \
you something, not only at the end."""


# The cross-vendor family (docs/PREREG-handoff-xvendor.md): after the cut, A's session is resumed
# once with this message and a few more turns, as when a person stops one tool to hand the task to
# another. It names no channel, so NOTES.md and the av records get the same chance.
WRAPUP_MESSAGE = """Stop here: your session is ending now, and another engineer, possibly using a different tool, will take over this task from your working tree. Do not change any code. Leave what they need to continue, then stop."""


def predecessor_instruction(goal):
    return goal.rstrip() + "\n\n" + NOTES_RULE + "\n"


def freeze_command(name="workspace"):
    """Tar /app as A left it (the av arm's /app is a symlink to the jj workspace).

    `workspace` is the tree B starts from; `workspace-cut` is the tree at the cut, before a
    wrap-up, kept only so `oe freeze` can say whether the wrap-up changed code.
    """
    ex = " ".join(f"--exclude={x}" for x in EXCLUDES)
    return (f"mkdir -p {FREEZE_DIR} && tar -C /app/ {ex} -czf {FREEZE_DIR}/{name}.tar.gz . "
            f"&& ls -la /app/ > {FREEZE_DIR}/ls-{name}.txt")
