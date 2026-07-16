from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.plan_task import parse_plan


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "plan_task.py"
PLAN_PATH = PROJECT_ROOT / "PLAN.md"


class PlanTaskCliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_no_argument_returns_first_task(self) -> None:
        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_id"], "A01")
        self.assertEqual(payload["next_task_id"], "A02")
        self.assertTrue(payload["content"].startswith("#### A01 "))
        self.assertNotIn("#### A02 ", payload["content"])

    def test_task_id_is_case_insensitive(self) -> None:
        result = self.run_cli("a05")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_id"], "A05")
        self.assertEqual(payload["next_task_id"], "B01")
        self.assertNotIn("### 阶段 B", payload["content"])

    def test_last_task_has_no_next_task(self) -> None:
        result = self.run_cli("J04")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_id"], "J04")
        self.assertIsNone(payload["next_task_id"])
        self.assertNotIn("## 6.", payload["content"])

    def test_unknown_task_fails_without_stdout(self) -> None:
        result = self.run_cli("Z99")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Unknown task ID: Z99", result.stderr)

    def test_duplicate_task_id_is_rejected(self) -> None:
        plan = """# Plan

## 子任务清单

### Stage

#### A01 First

First body.

#### A01 Duplicate

Second body.
"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = Path(temporary_dir) / "PLAN.md"
            plan_path.write_text(plan, encoding="utf-8")
            result = self.run_cli("--plan", str(plan_path))

        self.assertEqual(result.returncode, 2)
        self.assertIn("Duplicate task ID: A01", result.stderr)

    def test_task_section_end_is_not_included_in_last_task(self) -> None:
        plan = """# Plan

## 子任务清单

### Stage

#### A01 Only

Task body.

## Completion rules

Not task content.
"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = Path(temporary_dir) / "PLAN.md"
            plan_path.write_text(plan, encoding="utf-8")
            result = self.run_cli("--plan", str(plan_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["content"], "#### A01 Only\n\nTask body.")
        self.assertIsNone(payload["next_task_id"])

    def test_heading_inside_code_fence_is_not_a_task(self) -> None:
        plan = """# Plan

## 子任务清单

### Stage

```markdown
#### Z99 Not a task
```

#### A01 Real task

Task body.
"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            plan_path = Path(temporary_dir) / "PLAN.md"
            plan_path.write_text(plan, encoding="utf-8")
            result = self.run_cli("--plan", str(plan_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_id"], "A01")
        self.assertNotIn("Z99", payload["content"])

    def test_real_plan_contains_expected_number_of_tasks(self) -> None:
        tasks = parse_plan(PLAN_PATH)

        self.assertEqual(len(tasks), 45)
        self.assertEqual(len({task.task_id for task in tasks}), len(tasks))


if __name__ == "__main__":
    unittest.main()
