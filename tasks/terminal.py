"""Terminal-agent tasks: inspect a workspace, run commands, make the checker pass."""

TASKS = [
    # ----------------------------------------------------------------- term-01
    {
        "id": "term-01",
        "category": "terminal",
        "title": "diagnose a failing calculator",
        "difficulty": "easy",
        "mode": "agent",
        "no_think": True,
        "prompt": (
            "The workspace contains calc.py and verify.py. `python verify.py` fails.\n"
            "Run it, read the traceback, find the real bug and fix calc.py. "
            "Do not edit verify.py. Call finish when it passes."
        ),
        "files": {
            "calc.py": '''"""Tiny calculator used by the reports team."""


def add(a, b):
    return a + b


def divide(a, b):
    return a // b


def average(values):
    return divide(sum(values), len(values))
''',
            "verify.py": '''import calc

assert calc.add(2, 3) == 5
assert calc.divide(7, 2) == 3.5, calc.divide(7, 2)
assert calc.divide(-7, 2) == -3.5, calc.divide(-7, 2)
assert abs(calc.average([1, 2, 3, 4]) - 2.5) < 1e-9

try:
    calc.divide(1, 0)
    raise AssertionError("expected ZeroDivisionError")
except ZeroDivisionError:
    pass
print("ok")
''',
        },
        "oracle": {
            "calc.py": '''"""Tiny calculator used by the reports team."""


def add(a, b):
    return a + b


def divide(a, b):
    return a / b


def average(values):
    return divide(sum(values), len(values))
''',
        },
        "max_steps": 10,
        "max_tokens": 800,
    },
    # ----------------------------------------------------------------- term-02
    {
        "id": "term-02",
        "category": "terminal",
        "title": "repair invalid JSON config",
        "difficulty": "easy",
        "mode": "agent",
        "no_think": True,
        "prompt": (
            "`python verify.py` fails with a JSON parse error. Inspect conf/settings.json and "
            "fix the file so app.load() returns name=demo, retries=3, timeout=30. "
            "Do not edit app.py or verify.py. Call finish when it passes."
        ),
        "files": {
            "conf/settings.json": '''{
  "name": "demo",
  "retries": 3,
  "timeout": 30,
}
''',
            "app.py": '''"""Load configuration."""

import json


def load(path="conf/settings.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    print(load())
''',
            "verify.py": '''import json

import app

cfg = app.load()
assert cfg == {"name": "demo", "retries": 3, "timeout": 30}, cfg

with open("conf/settings.json", encoding="utf-8") as f:
    raw = json.load(f)
assert raw == cfg
print("ok")
''',
        },
        "oracle": {
            "conf/settings.json": '''{
  "name": "demo",
  "retries": 3,
  "timeout": 30
}
''',
        },
        "max_steps": 10,
        "max_tokens": 800,
    },
    # ----------------------------------------------------------------- term-03
    {
        "id": "term-03",
        "category": "terminal",
        "title": "rename a function across the workspace",
        "difficulty": "medium",
        "mode": "agent",
        "no_think": True,
        "prompt": (
            "Rename pricing.calc_total to pricing.compute_total everywhere: the definition and "
            "all callers in cart.py and report.py. Behaviour must not change and the old name "
            "must be gone. Run `python verify.py` to confirm, then call finish."
        ),
        "files": {
            "pricing.py": '''"""Price calculation."""


def calc_total(items):
    return sum(item["price"] * item["qty"] for item in items)
''',
            "cart.py": '''"""Cart helpers."""

from pricing import calc_total


def cart_total(items):
    return calc_total(items)
''',
            "report.py": '''"""Report helpers."""

import pricing


def line(items):
    return "total=%d" % pricing.calc_total(items)
''',
            "verify.py": '''import cart
import pricing
import report

items = [
    {"price": 2, "qty": 3},
    {"price": 5, "qty": 1},
]
assert pricing.compute_total(items) == 11
assert not hasattr(pricing, "calc_total"), "old name must be gone"
assert cart.cart_total(items) == 11
assert report.line(items) == "total=11"
print("ok")
''',
        },
        "oracle": {
            "pricing.py": '''"""Price calculation."""


def compute_total(items):
    return sum(item["price"] * item["qty"] for item in items)
''',
            "cart.py": '''"""Cart helpers."""

from pricing import compute_total


def cart_total(items):
    return compute_total(items)
''',
            "report.py": '''"""Report helpers."""

import pricing


def line(items):
    return "total=%d" % pricing.compute_total(items)
''',
        },
        "max_steps": 12,
        "max_tokens": 900,
    },
    # ----------------------------------------------------------------- term-04
    {
        "id": "term-04",
        "category": "terminal",
        "title": "run a generator, then write a summary file",
        "difficulty": "medium",
        "mode": "agent",
        "no_think": True,
        "prompt": (
            "Run generate.py to create sales.csv. Then inspect the CSV and write summary.json "
            "with exactly two keys: \"total\" (an integer) and \"by_region\" (an object mapping "
            "each region to its integer sum). Use the numbers from the file. "
            "Do not edit generate.py or verify.py. Call finish when `python verify.py` passes."
        ),
        "files": {
            "generate.py": '''"""Generate the sales file."""

ROWS = [
    ("north", 120),
    ("south", 80),
    ("north", 30),
    ("east", 50),
    ("south", 15),
    ("east", 25),
]


def main():
    with open("sales.csv", "w", encoding="utf-8", newline="") as f:
        f.write("region,amount\\n")
        for region, amount in ROWS:
            f.write("%s,%d\\n" % (region, amount))


if __name__ == "__main__":
    main()
''',
            "verify.py": '''import csv
import json
import os

assert os.path.exists("sales.csv"), "run generate.py first"

with open("sales.csv", encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 6, rows

expected_by_region = {}
for row in rows:
    region = row["region"]
    expected_by_region[region] = expected_by_region.get(region, 0) + int(row["amount"])
expected_total = sum(expected_by_region.values())

with open("summary.json", encoding="utf-8") as f:
    summary = json.load(f)

assert set(summary) == {"total", "by_region"}, summary
assert summary["total"] == expected_total, summary
assert summary["by_region"] == expected_by_region, summary
print("ok")
''',
        },
        "oracle": {
            "sales.csv": '''region,amount
north,120
south,80
north,30
east,50
south,15
east,25
''',
            "summary.json": '''{
  "total": 320,
  "by_region": {
    "north": 150,
    "south": 95,
    "east": 75
  }
}
''',
        },
        "max_steps": 14,
        "max_tokens": 1000,
    },
]
