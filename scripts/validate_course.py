#!/usr/bin/env python3
"""Validate educational content contracts consumed by both API and UI."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "course" / "curriculum.json"
course = json.loads(path.read_text(encoding="utf-8"))
assert len(course["weeks"]) == course["totalWeeks"] == 10, "需要 10 周课程"
seen = set()
total_hours = 0
for number, week in enumerate(course["weeks"], 1):
    assert week["number"] == number, f"周次错误：{week['id']}"
    assert len(week["tasks"]) == 3, f"每周需要 3 个任务：{week['id']}"
    assert sum(task["hours"] for task in week["tasks"]) == week["hours"] == 20
    for task in week["tasks"]:
        assert task["id"] not in seen, f"重复任务：{task['id']}"
        assert all(pre in seen for pre in task["prerequisites"]), f"前置任务必须已定义：{task['id']}"
        assert all(task[key] for key in ["title", "summary", "objectives", "deliverables", "acceptanceCriteria", "submissionPrompt"])
        assert len(task["tutorial"]) >= 3, f"教程不完整：{task['id']}"
        assert all(len(part["body"]) >= 100 for part in task["tutorial"]), f"教程段落太短：{task['id']}"
        assert len(task["steps"]) >= 4
        assert sum(item["weight"] for item in task["rubric"]) == 100, f"评分权重错误：{task['id']}"
        assert len({item["id"] for item in task["rubric"]}) == len(task["rubric"])
        assert all(item["weight"] > 0 for item in task["rubric"])
        assert all(resource["url"].startswith("https://") for resource in task["resources"])
        seen.add(task["id"])
        total_hours += task["hours"]
assert len(seen) == 30
assert total_hours == course["totalHours"] == 200
print(f"课程验证通过：10 周 / {len(seen)} 任务 / {total_hours} 小时 / 每任务评分权重 100")
