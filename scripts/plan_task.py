#!/usr/bin/env python3
"""Return one task from PLAN.md for an automated agent workflow."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TextIO

from markdown_it import MarkdownIt
from markdown_it.token import Token


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN_PATH = PROJECT_ROOT / "PLAN.md"
TASK_SECTION_TITLE = "子任务清单"


class PlanParseError(ValueError):
    """Raised when PLAN.md does not follow the required task structure."""


@dataclass(frozen=True)
class PlanTask:
    task_id: str
    content: str
    next_task_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "task_id": self.task_id,
            "content": self.content,
            "next_task_id": self.next_task_id,
        }


def _heading_level(token: Token) -> int:
    if token.type != "heading_open" or len(token.tag) != 2:
        raise PlanParseError(f"Unexpected heading token: {token.type} {token.tag}")
    return int(token.tag[1])


def _heading_text(tokens: list[Token], index: int) -> str:
    try:
        inline = tokens[index + 1]
    except IndexError as exc:
        raise PlanParseError("Heading is missing inline content") from exc
    if inline.type != "inline":
        raise PlanParseError("Heading is missing inline content")
    return inline.content.strip()


def _task_id_from_heading(heading: str) -> str | None:
    candidate = heading.split(maxsplit=1)[0].upper() if heading else ""
    if (
        len(candidate) == 3
        and candidate[0].isalpha()
        and candidate[0].isascii()
        and candidate[1:].isdigit()
        and candidate[1:].isascii()
    ):
        return candidate
    return None


def _task_section_bounds(tokens: list[Token]) -> tuple[int, int]:
    section_start: int | None = None

    for index, token in enumerate(tokens):
        if token.type != "heading_open" or _heading_level(token) != 2:
            continue
        if section_start is None:
            if _heading_text(tokens, index) == TASK_SECTION_TITLE:
                section_start = index + 3
            continue
        return section_start, index

    if section_start is None:
        raise PlanParseError(f'Missing "## {TASK_SECTION_TITLE}" section')
    return section_start, len(tokens)


def _task_end_line(
    tokens: list[Token], heading_index: int, section_end: int, line_count: int
) -> int:
    for token in tokens[heading_index + 1 : section_end]:
        if token.type == "heading_open" and _heading_level(token) <= 4:
            if token.map is None:
                raise PlanParseError("Heading is missing source line information")
            return token.map[0]
    if section_end < len(tokens):
        section_end_token = tokens[section_end]
        if section_end_token.map is None:
            raise PlanParseError("Task section end has no source line information")
        return section_end_token.map[0]
    return line_count


def parse_plan(plan_path: Path = DEFAULT_PLAN_PATH) -> list[PlanTask]:
    try:
        source = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlanParseError(f"Cannot read plan file {plan_path}: {exc}") from exc

    tokens = MarkdownIt("commonmark").parse(source)
    lines = source.splitlines()
    section_start, section_end = _task_section_bounds(tokens)
    parsed_tasks: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    for index in range(section_start, section_end):
        token = tokens[index]
        if token.type != "heading_open" or _heading_level(token) != 4:
            continue

        task_id = _task_id_from_heading(_heading_text(tokens, index))
        if task_id is None:
            continue
        if task_id in seen_ids:
            raise PlanParseError(f"Duplicate task ID: {task_id}")
        if token.map is None:
            raise PlanParseError(
                f"Task heading {task_id} has no source line information"
            )

        end_line = _task_end_line(tokens, index, section_end, len(lines))
        content = "\n".join(lines[token.map[0] : end_line]).strip()
        if not content:
            raise PlanParseError(f"Task {task_id} has no content")

        seen_ids.add(task_id)
        parsed_tasks.append((task_id, content))

    if not parsed_tasks:
        raise PlanParseError("No task headings were found in the task section")

    return [
        PlanTask(
            task_id=task_id,
            content=content,
            next_task_id=(
                parsed_tasks[index + 1][0] if index + 1 < len(parsed_tasks) else None
            ),
        )
        for index, (task_id, content) in enumerate(parsed_tasks)
    ]


def select_task(tasks: list[PlanTask], requested_id: str | None) -> PlanTask:
    if not tasks:
        raise PlanParseError("No tasks are available")
    if requested_id is None:
        return tasks[0]

    normalized_id = requested_id.upper()
    for task in tasks:
        if task.task_id == normalized_id:
            return task
    raise PlanParseError(f"Unknown task ID: {requested_id}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Return one PLAN.md task and the next task ID as JSON."
    )
    parser.add_argument(
        "task_id",
        nargs="?",
        help="Task ID such as A01. Defaults to the first task.",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PLAN_PATH,
        help=f"Plan path. Defaults to {DEFAULT_PLAN_PATH}.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _build_parser().parse_args(argv)
    try:
        task = select_task(parse_plan(args.plan), args.task_id)
    except PlanParseError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    json.dump(task.as_dict(), stdout, ensure_ascii=False, indent=2)
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
