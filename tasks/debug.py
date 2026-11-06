"""Debugging tasks: a failing test suite plus buggy code. Fix the code, keep the spec."""

TASKS = [
    {
        "id": "dbg-01",
        "category": "debug",
        "title": "pagination off-by-one",
        "difficulty": "easy",
        "mode": "edit",
        "prompt": (
            "The tests in tests.py fail. Pages are supposed to be 1-indexed: page 1 returns the "
            "first `size` items, page 2 the next block, and a page past the end returns []. "
            "Fix paging.py. Do not change tests.py."
        ),
        "write_to": "paging.py",
        "files": {
            "paging.py": r'''"""Pagination."""


def paginate(items, page, size):
    if page < 1:
        raise ValueError("page must be >= 1")
    if size < 1:
        raise ValueError("size must be >= 1")
    start = page * size
    return items[start:start + size]
''',
            "tests.py": r'''
import paging as m

items = list(range(1, 11))
assert m.paginate(items, 1, 3) == [1, 2, 3], m.paginate(items, 1, 3)
assert m.paginate(items, 2, 3) == [4, 5, 6]
assert m.paginate(items, 4, 3) == [10]
assert m.paginate(items, 5, 3) == []
try:
    m.paginate(items, 0, 3)
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("ok")
''',
        },
        "fixes": [("    start = page * size", "    start = (page - 1) * size")],
        "max_tokens": 600,
    },
    {
        "id": "dbg-02",
        "category": "debug",
        "title": "shared mutable default argument",
        "difficulty": "easy",
        "mode": "edit",
        "prompt": (
            "The tests in tests.py fail because separate calls share state. Each call must start "
            "from a fresh list unless the caller passes one explicitly. Fix tags.py."
        ),
        "write_to": "tags.py",
        "files": {
            "tags.py": r'''"""Tag helpers."""


def add_tag(tag, tags=[]):
    tags.append(tag)
    return tags
''',
            "tests.py": r'''
import tags as m

a = m.add_tag("x")
b = m.add_tag("y")
assert a == ["x"], a
assert b == ["y"], b
assert m.add_tag("z", ["q"]) == ["q", "z"]
assert m.add_tag("w") == ["w"]
print("ok")
''',
        },
        "fixes": [(
            "def add_tag(tag, tags=[]):\n    tags.append(tag)\n    return tags\n",
            'def add_tag(tag, tags=None):\n    if tags is None:\n        tags = []\n    tags.append(tag)\n    return tags\n',
        )],
        "max_tokens": 500,
    },
    {
        "id": "dbg-03",
        "category": "debug",
        "title": "cent-losing bill split",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "split_bill(total_cents, people) must return a list of integer cents that sums exactly "
            "to total_cents, with no two shares differing by more than 1 cent. Deterministic: the "
            "earlier people get the extra cent. The tests fail; fix bill.py."
        ),
        "write_to": "bill.py",
        "files": {
            "bill.py": r'''"""Bill splitting."""


def split_bill(total_cents, people):
    if people < 1:
        raise ValueError("people must be >= 1")
    share = round(total_cents / people)
    return [share] * people
''',
            "tests.py": r'''
import bill as m

for total, people in [(1000, 3), (999, 7), (1, 3), (100, 4), (0, 2)]:
    parts = m.split_bill(total, people)
    assert len(parts) == people, (total, people, parts)
    assert sum(parts) == total, (total, people, parts)
    assert max(parts) - min(parts) <= 1, (total, people, parts)
assert m.split_bill(1000, 3) == [334, 333, 333], m.split_bill(1000, 3)
assert m.split_bill(999, 7) == [143, 143, 143, 143, 143, 142, 142]
try:
    m.split_bill(100, 0)
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("ok")
''',
        },
        "fixes": [(
            "    share = round(total_cents / people)\n    return [share] * people",
            "    base, rem = divmod(total_cents, people)\n    return [base + 1] * rem + [base] * (people - rem)",
        )],
        "max_tokens": 700,
    },
    {
        "id": "dbg-04",
        "category": "debug",
        "title": "class attribute shared by instances",
        "difficulty": "easy",
        "mode": "edit",
        "prompt": (
            "Two Cart instances must never share their contents. The tests fail; fix cart.py "
            "without changing the public API."
        ),
        "write_to": "cart.py",
        "files": {
            "cart.py": r'''"""Shopping cart."""


class Cart:
    items = []

    def add(self, item):
        self.items.append(item)
        return self.items

    def total(self):
        return sum(i["price"] for i in self.items)
''',
            "tests.py": r'''
import cart as m

a = m.Cart()
b = m.Cart()
a.add("x")
b.add("y")
assert a.items == ["x"], a.items
assert b.items == ["y"], b.items
assert a.items is not b.items
c = m.Cart()
c.add({"price": 5})
c.add({"price": 7})
assert c.total() == 12
assert m.Cart().items == []
print("ok")
''',
        },
        "fixes": [(
            'class Cart:\n    items = []\n\n    def add',
            'class Cart:\n    def __init__(self):\n        self.items = []\n\n    def add',
        )],
        "max_tokens": 600,
    },
    {
        "id": "dbg-05",
        "category": "debug",
        "title": "over-broad exception catching",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "get_setting must raise KeyError when the key is absent, and must not swallow programming "
            "errors such as passing None instead of a dict. Fix settings.py."
        ),
        "write_to": "settings.py",
        "files": {
            "settings.py": r'''"""Config access."""


def get_setting(cfg, key):
    try:
        return cfg[key]
    except Exception:
        return None
''',
            "tests.py": r'''
import settings as m

assert m.get_setting({"a": 1}, "a") == 1
try:
    m.get_setting({}, "a")
    raise AssertionError("expected KeyError")
except KeyError:
    pass
try:
    m.get_setting(None, "a")
    raise AssertionError("expected TypeError")
except TypeError:
    pass
print("ok")
''',
        },
        "fixes": [(
            'def get_setting(cfg, key):\n    try:\n        return cfg[key]\n    except Exception:\n        return None\n',
            'def get_setting(cfg, key):\n    return cfg[key]\n',
        )],
        "max_tokens": 500,
    },
    {
        "id": "dbg-06",
        "category": "debug",
        "title": "bytes vs str from file read",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "read_names(path) must return a list of upper-cased str names, one per line, ignoring "
            "blank lines. The file is UTF-8. The tests fail; fix names.py."
        ),
        "write_to": "names.py",
        "files": {
            "names.py": r'''"""Name loading."""


def read_names(path):
    with open(path, "rb") as f:
        data = f.read()
    return [line.upper() for line in data.split(b"\n") if line]
''',
            "tests.py": r'''
import os
import tempfile
import names as m

fd, path = tempfile.mkstemp(suffix=".txt")
os.close(fd)
with open(path, "w", encoding="utf-8") as f:
    f.write("ada\nGrace\n\nlinus\n")

got = m.read_names(path)
assert got == ["ADA", "GRACE", "LINUS"], got
assert all(isinstance(x, str) for x in got), got
os.unlink(path)
print("ok")
''',
        },
        "fixes": [(
            '    with open(path, "rb") as f:\n        data = f.read()\n    return [line.upper() for line in data.split(b"\\n") if line]',
            '    with open(path, "r", encoding="utf-8") as f:\n        lines = f.read().splitlines()\n    return [line.upper() for line in lines if line.strip()]',
        )],
        "max_tokens": 600,
    },
    {
        "id": "dbg-07",
        "category": "debug",
        "title": "cache key collision",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "render(template, value) is memoised but returns stale output for different values. "
            "Cache entries must be keyed by everything that affects the result. Fix render.py."
        ),
        "write_to": "render.py",
        "files": {
            "render.py": r'''"""Template rendering with a cache."""

_cache = {}


def render(template, value):
    key = template
    if key not in _cache:
        _cache[key] = template.format(v=value)
    return _cache[key]


def clear_cache():
    _cache.clear()
''',
            "tests.py": r'''
import render as m

assert m.render("{v}-a", "1") == "1-a"
assert m.render("{v}-b", "2") == "2-b"
assert m.render("{v}-a", "1") == "1-a"
assert m.render("{v}-a", "9") == "9-a"
m.clear_cache()
assert m.render("{v}-a", "1") == "1-a"
print("ok")
''',
        },
        "fixes": [("    key = template", "    key = (template, value)")],
        "max_tokens": 500,
    },
    {
        "id": "dbg-08",
        "category": "debug",
        "title": "loose regex and wrong return types",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "parse_version(text) must return a tuple of three ints for a version written exactly as "
            "vMAJOR.MINOR.PATCH somewhere in the text, and raise ValueError when there is no complete "
            "version. The tests fail; fix version.py."
        ),
        "write_to": "version.py",
        "files": {
            "version.py": r'''"""Version parsing."""

import re


def parse_version(text):
    m = re.search(r"v(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    a, b, c = m.groups()
    return (a, b, c)
''',
            "tests.py": r'''
import version as m

assert m.parse_version("release v1.2.3 build") == (1, 2, 3)
assert m.parse_version("v10.0.11") == (10, 0, 11)
assert m.parse_version("tag=v0.0.1") == (0, 0, 1)
for bad in ["v1.2", "no version here", "v1.2.3.4beta"]:
    try:
        m.parse_version(bad)
        raise AssertionError("expected ValueError for %r" % bad)
    except ValueError:
        pass
print("ok")
''',
        },
        "fixes": [(
            '    m = re.search(r"v(\\d+)\\.(\\d+)(?:\\.(\\d+))?", text)\n    if not m:\n        return None\n    a, b, c = m.groups()\n    return (a, b, c)',
            '    m = re.search(r"(?<![\\d.])v(\\d+)\\.(\\d+)\\.(\\d+)(?![\\d.])", text)\n    if not m:\n        raise ValueError("no version in %r" % (text,))\n    return tuple(int(g) for g in m.groups())',
        )],
        "max_tokens": 600,
    },
]
