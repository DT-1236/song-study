"""Token use of a Claude Code session, split into phases, for the ledger in
docs/token-usage.md.

    python3 scripts/token_usage.py [SESSION_ID] [--top N]

SESSION_ID defaults to $CLAUDE_CODE_SESSION_ID, the session running it; a
unique prefix of an id is enough. A phase starts at each prompt the user
types and at each skill the session runs (such as /simplify), and a
subagent's use counts toward the phase that started it. --top lists the N
tool calls whose results grew the main thread's context most, for a
post-mortem.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

# Upper bounds, in tokens of input read, of the sizes docs/token-usage.md
# defines.
SIZES = [("S", 1_000_000), ("M", 5_000_000), ("L", 15_000_000)]


def size(input_read: int) -> str:
    """The size bucket of a phase or session that read `input_read` tokens."""
    for name, bound in SIZES:
        if input_read < bound:
            return name
    return "XL"


@dataclass
class Phase:
    label: str
    started: str
    calls: int = 0
    peak: int = 0
    input_read: int = 0
    output: int = 0
    models: set = field(default_factory=set)
    subagents: int = 0

    def add(self, usage: dict, model: str | None) -> int:
        """Count one API call and return the context it sent."""
        context = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        self.calls += 1
        self.peak = max(self.peak, context)
        self.input_read += context
        self.output += usage.get("output_tokens", 0)
        if model and not model.startswith("<"):
            self.models.add(model)
        return context


def records(path: Path):
    with open(path) as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def text_of(record: dict) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return ""


def phase_start(record: dict) -> str | None:
    """The label of the phase `record` starts, if it's a typed prompt or a
    slash command."""
    if record.get("type") != "user" or record.get("isMeta"):
        return None
    text = text_of(record).strip()
    if "<command-name>" in text:
        command = text.split("<command-name>")[1].split("</command-name>")[0]
        # Commands that only change settings start no work of their own.
        if command in ("/clear", "/model", "/effort", "/fast", "/config", "/cost"):
            return None
        return command
    origin = record.get("origin") or {}
    # Older transcripts have no `origin`; a typed prompt is then the plain
    # text that isn't a tool result or a harness notice.
    typed = origin.get("kind") == "human" or (
        not origin
        and text
        and not text.startswith("<")
        and "toolUseResult" not in record
    )
    if not typed:
        return None
    first_line = text.splitlines()[0]
    return f'"{first_line[:40]}{"…" if len(first_line) > 40 else ""}"'


def describe(tool_use: dict) -> str:
    args = tool_use.get("input") or {}
    detail = (
        args.get("description")
        or args.get("file_path")
        or args.get("skill")
        or args.get("command", "")[:60]
    )
    return f"{tool_use.get('name')}: {detail}"


def session_files(session: str) -> tuple[Path, list[Path]]:
    matches = sorted(PROJECTS.glob(f"*/{session}*.jsonl"))
    if len(matches) != 1:
        found = ", ".join(m.stem for m in matches) or "none"
        sys.exit(f"expected one session matching {session!r}, found: {found}")
    main = matches[0]
    return main, sorted((main.parent / main.stem / "subagents").glob("*.jsonl"))


def measure(main: Path, subagents: list[Path]):
    phases = [Phase("(session start)", "")]
    growth = []  # (tokens, what caused them) along the main thread
    seen = set()
    previous_context = 0
    # The tool calls of the API call before the current one, whose results
    # are what the current one's context grew by.
    calls_tools = ["(session start)"]
    for record in records(main):
        if label := phase_start(record):
            phases.append(Phase(label, record.get("timestamp", "")))
        message = record.get("message") or {}
        if record.get("type") != "assistant" or "usage" not in message:
            continue
        tool_uses = [
            b for b in message.get("content", []) if b.get("type") == "tool_use"
        ]
        for tool_use in tool_uses:
            if tool_use.get("name") == "Skill":
                skill = (tool_use.get("input") or {}).get("skill")
                phases.append(Phase(f"/{skill}", record.get("timestamp", "")))
        described = [describe(t) for t in tool_uses]
        # One API call can be split over several transcript lines (thinking,
        # text, each tool call), each repeating its usage.
        if message.get("id") in seen:
            calls_tools.extend(described)
            continue
        seen.add(message.get("id"))
        context = phases[-1].add(message["usage"], message.get("model"))
        if context > previous_context:
            growth.append(
                (context - previous_context, "; ".join(calls_tools) or "(reply)")
            )
        previous_context = context
        calls_tools = described

    for path in subagents:
        started = next(
            (r.get("timestamp") for r in records(path) if r.get("timestamp")), ""
        )
        # The last phase that had started when the subagent did.
        owner = max(
            (p for p in phases if p.started <= started), key=lambda p: p.started
        )
        owner.subagents += 1
        seen = set()
        for record in records(path):
            message = record.get("message") or {}
            if record.get("type") != "assistant" or "usage" not in message:
                continue
            if message.get("id") in seen:
                continue
            seen.add(message.get("id"))
            owner.add(message["usage"], message.get("model"))
    return [p for p in phases if p.calls], growth


def tokens(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1_000_000 else f"{n / 1e3:.0f}k"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID")
    )
    parser.add_argument("--top", type=int, default=0)
    args = parser.parse_args()
    if not args.session:
        sys.exit("no session id given, and CLAUDE_CODE_SESSION_ID isn't set")

    path, subagents = session_files(args.session)
    phases, growth = measure(path, subagents)
    print(f"session {path.stem}")
    # Effort isn't in the transcript; it's only known for the session running
    # this.
    if path.stem == os.environ.get("CLAUDE_CODE_SESSION_ID"):
        print(f"effort {os.environ.get('CLAUDE_EFFORT', 'unknown')}")
    header = f"{'phase':<46} {'calls':>5} {'peak':>6} {'input':>7} {'output':>6}  size  models"
    print(header)
    for phase in phases:
        label = phase.label + (
            f" (+{phase.subagents} subagents)" if phase.subagents else ""
        )
        print(
            f"{label[:46]:<46} {phase.calls:>5} {tokens(phase.peak):>6} "
            f"{tokens(phase.input_read):>7} {tokens(phase.output):>6}  "
            f"{size(phase.input_read):<4}  {', '.join(sorted(phase.models))}"
        )
    total_read = sum(p.input_read for p in phases)
    print(
        f"{'total':<46} {sum(p.calls for p in phases):>5} {'':>6} "
        f"{tokens(total_read):>7} {tokens(sum(p.output for p in phases)):>6}  "
        f"{size(total_read)}"
    )
    if args.top:
        print(
            "\nlargest context growth on the main thread (re-read on every later call):"
        )
        for amount, cause in sorted(growth, reverse=True)[: args.top]:
            print(f"  +{tokens(amount):>5}  {cause[:100]}")


if __name__ == "__main__":
    main()
