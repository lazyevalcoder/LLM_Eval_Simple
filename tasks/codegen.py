"""Code generation tasks: implement a module from a spec, tests are the spec."""

TASKS = [
    {
        "id": "cg-01",
        "category": "codegen",
        "title": "Apache-style log parsing + summary",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Implement `parse_line(line)` and `summarize(lines)` in parse_logs.py.\n\n"
            "parse_line parses one Apache combined-ish log line:\n"
            '  10.0.0.1 - - [12/Mar/2026:10:11:12 +0000] "GET /a/b?x=1 HTTP/1.1" 200 512\n'
            "and returns a dict with keys ip (str), ts (str, the part inside []), method (str), "
            'path (str), status (int), bytes (int, or None when the field is "-").\n'
            "Raise ValueError for anything that does not match the format.\n\n"
            "summarize(lines) returns {\"total\": int, \"by_status\": {status: count}, "
            "\"error_rate\": float} where error_rate is the fraction of statuses >= 400 "
            "(0.0 when there are no lines).\n\n"
            "Keep the function names and module name exactly as the tests expect."
        ),
        "write_to": "parse_logs.py",
        "files": {
            "parse_logs.py": '"""Log parsing utilities."""\n\n\ndef parse_line(line):\n    raise NotImplementedError\n\n\ndef summarize(lines):\n    raise NotImplementedError\n',
            "tests.py": r'''
import parse_logs as m

LINE = '10.0.0.1 - - [12/Mar/2026:10:11:12 +0000] "GET /a/b?x=1 HTTP/1.1" 200 512'
r = m.parse_line(LINE)
assert r == {
    "ip": "10.0.0.1",
    "ts": "12/Mar/2026:10:11:12 +0000",
    "method": "GET",
    "path": "/a/b?x=1",
    "status": 200,
    "bytes": 512,
}, r

r2 = m.parse_line('1.2.3.4 - - [x] "POST / HTTP/2" 404 -')
assert r2["status"] == 404 and r2["bytes"] is None, r2

for bad in ["garbage", "", '1.2.3.4 - - "GET / HTTP/1.1" 200 5']:
    try:
        m.parse_line(bad)
        raise AssertionError("expected ValueError for %r" % bad)
    except ValueError:
        pass

lines = [
    LINE,
    '1.2.3.4 - - [x] "POST / HTTP/2" 404 -',
    '2.2.2.2 - - [y] "GET / HTTP/1.1" 500 0',
]
s = m.summarize(lines)
assert s["total"] == 3, s
assert s["by_status"] == {200: 1, 404: 1, 500: 1}, s
assert abs(s["error_rate"] - 2 / 3) < 1e-9, s
assert m.summarize([]) == {"total": 0, "by_status": {}, "error_rate": 0.0}
print("ok")
''',
        },
        "oracle": {
            "parse_logs.py": r'''"""Log parsing utilities."""

import re

_LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) [^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\S+)$'
)


def parse_line(line):
    m = _LINE.match(line.strip())
    if not m:
        raise ValueError("cannot parse log line: %r" % (line,))
    nbytes = m.group("bytes")
    return {
        "ip": m.group("ip"),
        "ts": m.group("ts"),
        "method": m.group("method"),
        "path": m.group("path"),
        "status": int(m.group("status")),
        "bytes": None if nbytes == "-" else int(nbytes),
    }


def summarize(lines):
    by_status = {}
    errors = 0
    total = 0
    for line in lines:
        if not line.strip():
            continue
        rec = parse_line(line)
        total += 1
        by_status[rec["status"]] = by_status.get(rec["status"], 0) + 1
        if rec["status"] >= 400:
            errors += 1
    return {
        "total": total,
        "by_status": by_status,
        "error_rate": (errors / total) if total else 0.0,
    }
''',
        },
        "max_tokens": 1600,
    },
    {
        "id": "cg-02",
        "category": "codegen",
        "title": "sliding-window rate limiter with injected clock",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Implement `SlidingWindowLimiter` in ratelimit.py.\n\n"
            "Signature: SlidingWindowLimiter(max_calls, window_seconds, clock)\n"
            "- clock is a zero-argument callable returning the current time in seconds (float).\n"
            "- allow(key) returns True and records the call if the key has made fewer than "
            "max_calls calls in the trailing window_seconds, else returns False and records nothing.\n"
            "- remaining(key) returns how many calls the key can still make right now.\n"
            "- Keys are independent.\n\n"
            "The window is half-open: a call made exactly window_seconds ago no longer counts."
        ),
        "write_to": "ratelimit.py",
        "files": {
            "ratelimit.py": '"""Sliding window rate limiting."""\n\n\nclass SlidingWindowLimiter:\n    def __init__(self, max_calls, window_seconds, clock):\n        raise NotImplementedError\n\n    def allow(self, key):\n        raise NotImplementedError\n\n    def remaining(self, key):\n        raise NotImplementedError\n',
            "tests.py": r'''
import ratelimit as m


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


c = Clock()
lim = m.SlidingWindowLimiter(max_calls=3, window_seconds=10, clock=c.now)
assert [lim.allow("a") for _ in range(4)] == [True, True, True, False], "first burst"
assert lim.remaining("a") == 0
assert lim.allow("b") is True, "keys independent"
assert lim.remaining("b") == 2
c.t = 10.1
assert lim.allow("a") is True, "window expired"
assert lim.remaining("a") == 2
assert lim.allow("a") is True
assert lim.allow("a") is True
assert lim.allow("a") is False
print("ok")
''',
        },
        "oracle": {
            "ratelimit.py": r'''"""Sliding window rate limiting."""

from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_calls, window_seconds, clock):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.clock = clock
        self._calls = {}

    def _prune(self, key, now):
        q = self._calls.get(key)
        if not q:
            return q
        cutoff = now - self.window_seconds
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def allow(self, key):
        now = self.clock()
        q = self._prune(key, now)
        if q is None:
            q = self._calls[key] = deque()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True

    def remaining(self, key):
        q = self._prune(key, self.clock())
        used = len(q) if q else 0
        return max(0, self.max_calls - used)
''',
        },
        "max_tokens": 1400,
    },
    {
        "id": "cg-03",
        "category": "codegen",
        "title": "grouping + aggregation with tuple keys",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Implement group_by, aggregate and totals in grouping.py.\n\n"
            "group_by(rows, key_fields) -> dict mapping the tuple of key field values to the list "
            "of rows, preserving first-seen key order and row order within each bucket.\n"
            "aggregate(rows, key_fields, value_field) -> dict mapping the key tuple to the sum of "
            "the numeric value field.\n"
            "totals(rows, key_fields) -> same as aggregate but summing the field 'n'.\n\n"
            "All keys are tuples even when key_fields has one element."
        ),
        "write_to": "grouping.py",
        "files": {
            "grouping.py": '"""Grouping helpers."""\n\n\ndef group_by(rows, key_fields):\n    raise NotImplementedError\n\n\ndef aggregate(rows, key_fields, value_field):\n    raise NotImplementedError\n\n\ndef totals(rows, key_fields):\n    raise NotImplementedError\n',
            "tests.py": r'''
import grouping as m

rows = [
    {"team": "a", "region": "x", "n": 1},
    {"team": "a", "region": "y", "n": 2},
    {"team": "b", "region": "x", "n": 3},
    {"team": "a", "region": "x", "n": 4},
]
g = m.group_by(rows, ["team", "region"])
assert list(g.keys()) == [("a", "x"), ("a", "y"), ("b", "x")], list(g.keys())
assert [r["n"] for r in g[("a", "x")]] == [1, 4], g[("a", "x")]
assert m.aggregate(rows, ["team"], "n") == {("a",): 7, ("b",): 3}
assert m.totals(rows, ["team", "region"]) == {("a", "x"): 5, ("a", "y"): 2, ("b", "x"): 3}
assert m.group_by([], ["x"]) == {}
print("ok")
''',
        },
        "oracle": {
            "grouping.py": r'''"""Grouping helpers."""


def _key(row, fields):
    return tuple(row[f] for f in fields)


def group_by(rows, key_fields):
    out = {}
    for row in rows:
        out.setdefault(_key(row, key_fields), []).append(row)
    return out


def aggregate(rows, key_fields, value_field):
    out = {}
    for row in rows:
        k = _key(row, key_fields)
        out[k] = out.get(k, 0) + row[value_field]
    return out


def totals(rows, key_fields):
    return aggregate(rows, key_fields, "n")
''',
        },
        "max_tokens": 1200,
    },
    {
        "id": "cg-04",
        "category": "codegen",
        "title": "retry decorator with injected clock",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Implement `retry(...)` in retry.py as a decorator factory.\n\n"
            "Signature: retry(times, base_delay, exceptions, clock, sleeper)\n"
            "- Owns a monotonic clock callable; sleeper(seconds) advances it (tests fake both).\n"
            "- Calls the function up to `times` times total.\n"
            "- Between attempts sleeps base_delay * 2 ** (attempt-1), so 0.5, 1.0, 2.0 for base 0.5.\n"
            "- Re-raises immediately if the exception type is not in `exceptions`.\n"
            "- Re-raises the last exception once attempts are exhausted.\n"
            "- Preserves __name__ and __doc__ (use functools.wraps).\n"
            "- Clocks/sleepers are optional dependencies for the decorator only, never passed to the "
            "wrapped function."
        ),
        "write_to": "retry.py",
        "files": {
            "retry.py": '"""Retry helper."""\n\n\ndef retry(times, base_delay, exceptions, clock, sleeper):\n    raise NotImplementedError\n',
            "tests.py": r'''
import retry as m

sleeps = []
t = [0.0]


def clock():
    return t[0]


def sleeper(s):
    sleeps.append(s)
    t[0] += s


calls = {"n": 0}


@m.retry(times=4, base_delay=0.5, exceptions=(ValueError,), clock=clock, sleeper=sleeper)
def flaky():
    """flaky doc"""
    calls["n"] += 1
    if calls["n"] < 4:
        raise ValueError("boom")
    return "ok"


assert flaky() == "ok"
assert sleeps == [0.5, 1.0, 2.0], sleeps
assert calls["n"] == 4
assert flaky.__name__ == "flaky"
assert flaky.__doc__ == "flaky doc"

try:
    @m.retry(times=2, base_delay=0.1, exceptions=(KeyError,), clock=clock, sleeper=sleeper)
    def always():
        raise KeyError("x")
    always()
    raise AssertionError("expected KeyError to propagate")
except KeyError:
    pass

n = {"v": 0}


@m.retry(times=3, base_delay=0.1, exceptions=(ValueError,), clock=clock, sleeper=sleeper)
def wrong_type():
    n["v"] += 1
    raise TypeError("nope")


try:
    wrong_type()
    raise AssertionError("expected TypeError")
except TypeError:
    pass
assert n["v"] == 1, "must not retry unlisted exceptions"
print("ok")
''',
        },
        "oracle": {
            "retry.py": r'''"""Retry helper."""

import functools


def retry(times, base_delay, exceptions, clock, sleeper):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, times + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleeper(delay)
                    delay *= 2
        return wrapper
    return deco
''',
        },
        "max_tokens": 1400,
    },
    {
        "id": "cg-05",
        "category": "codegen",
        "title": "semver parse/compare/satisfies",
        "difficulty": "hard",
        "mode": "edit",
        "prompt": (
            "Implement parse, compare and satisfies in semver.py.\n\n"
            "parse(text) accepts exactly MAJOR.MINOR.PATCH (each one or more digits, nothing else) "
            "and returns a tuple of ints. Raise ValueError otherwise.\n"
            "compare(a, b) takes two version strings and returns -1, 0 or 1.\n"
            "satisfies(version, spec) supports: exact ('1.2.3'), '^x.y.z' (>= x.y.z and < next major, "
            "unless x == 0, in which case < next minor), '~x.y.z' (>= x.y.z and < next minor), "
            "and '>=x.y.z'.\n"
            "Raise ValueError for an unrecognised spec."
        ),
        "write_to": "semver.py",
        "files": {
            "semver.py": '"""Tiny semver helper."""\n\n\ndef parse(text):\n    raise NotImplementedError\n\n\ndef compare(a, b):\n    raise NotImplementedError\n\n\ndef satisfies(version, spec):\n    raise NotImplementedError\n',
            "tests.py": r'''
import semver as m

assert m.parse("1.2.3") == (1, 2, 3)
assert m.parse("10.0.11") == (10, 0, 11)
assert m.compare("1.2.3", "1.2.10") == -1
assert m.compare("2.0.0", "2.0.0") == 0
assert m.compare("2.1.0", "2.0.9") == 1
assert m.satisfies("1.4.2", "^1.2.0") is True
assert m.satisfies("2.0.0", "^1.2.0") is False
assert m.satisfies("1.1.9", "^1.2.0") is False
assert m.satisfies("1.2.9", "~1.2.3") is True
assert m.satisfies("1.3.0", "~1.2.3") is False
assert m.satisfies("1.2.3", ">=1.2.0") is True
assert m.satisfies("1.1.0", ">=1.2.0") is False
assert m.satisfies("1.2.3", "1.2.3") is True
assert m.satisfies("1.2.4", "1.2.3") is False
assert m.satisfies("0.3.9", "^0.3.0") is True
assert m.satisfies("0.4.0", "^0.3.0") is False
for bad in ["1.2", "1.2.3.4", "v1.2.3", ""]:
    try:
        m.parse(bad)
        raise AssertionError("expected ValueError for %r" % bad)
    except ValueError:
        pass
try:
    m.satisfies("1.2.3", "<=1.0.0")
    raise AssertionError("expected ValueError for unknown spec")
except ValueError:
    pass
print("ok")
''',
        },
        "oracle": {
            "semver.py": r'''"""Tiny semver helper."""

import re

_EXACT = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse(text):
    m = _EXACT.match(text.strip())
    if not m:
        raise ValueError("bad version: %r" % (text,))
    return tuple(int(g) for g in m.groups())


def compare(a, b):
    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)


def satisfies(version, spec):
    spec = spec.strip()
    v = parse(version)
    if spec.startswith("^"):
        lo = parse(spec[1:])
        if v < lo:
            return False
        hi = (lo[0] + 1, 0, 0) if lo[0] > 0 else (0, lo[1] + 1, 0)
        return v < hi
    if spec.startswith("~"):
        lo = parse(spec[1:])
        if v < lo:
            return False
        return v < (lo[0], lo[1] + 1, 0)
    if spec.startswith(">="):
        return v >= parse(spec[2:])
    if _EXACT.match(spec):
        return v == parse(spec)
    raise ValueError("bad spec: %r" % (spec,))
''',
        },
        "max_tokens": 1600,
    },
    {
        "id": "cg-06",
        "category": "codegen",
        "title": "deterministic topological sort with cycle reporting",
        "difficulty": "medium",
        "mode": "edit",
        "prompt": (
            "Implement topo_sort and CycleError in graph.py.\n\n"
            "topo_sort(nodes, edges) returns a list of all node names in dependency order, where an "
            "edge (a, b) means a must come before b. When several nodes are ready at the same time, "
            "pick them in lexicographic order so the output is deterministic.\n"
            "Raise CycleError (subclass of ValueError) with a .nodes attribute holding the set of "
            "node names involved in the cycle (including self-loops).\n"
            "Unknown nodes referenced only in edges should be treated as valid nodes."
        ),
        "write_to": "graph.py",
        "files": {
            "graph.py": '"""Graph utilities."""\n\n\nclass CycleError(ValueError):\n    def __init__(self, nodes):\n        super().__init__("cycle: %s" % (sorted(nodes),))\n        self.nodes = set(nodes)\n\n\ndef topo_sort(nodes, edges):\n    raise NotImplementedError\n',
            "tests.py": r'''
import graph as m

order = m.topo_sort(["d", "a", "b", "c"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
assert order == ["a", "b", "c", "d"], order
assert m.topo_sort(["z"], []) == ["z"]
assert m.topo_sort([], []) == []
order2 = m.topo_sort(["a", "b", "c"], [])
assert order2 == ["a", "b", "c"], order2
assert m.topo_sort(["b"], [("a", "b")]) == ["a", "b"]

try:
    m.topo_sort(["a", "b"], [("a", "b"), ("b", "a")])
    raise AssertionError("expected CycleError")
except m.CycleError as e:
    assert set(e.nodes) == {"a", "b"}, e.nodes
    assert isinstance(e, ValueError)
try:
    m.topo_sort(["a"], [("a", "a")])
    raise AssertionError("expected CycleError for self-loop")
except m.CycleError as e:
    assert e.nodes == {"a"}, e.nodes
print("ok")
''',
        },
        "oracle": {
            "graph.py": r'''"""Graph utilities."""

import heapq


class CycleError(ValueError):
    def __init__(self, nodes):
        super().__init__("cycle: %s" % (sorted(nodes),))
        self.nodes = set(nodes)


def topo_sort(nodes, edges):
    all_nodes = set(nodes)
    for a, b in edges:
        all_nodes.add(a)
        all_nodes.add(b)

    indeg = {n: 0 for n in all_nodes}
    adj = {n: [] for n in all_nodes}
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1

    ready = [n for n in all_nodes if indeg[n] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(ready, m)
    if len(out) != len(all_nodes):
        raise CycleError({n for n in all_nodes if indeg[n] > 0})
    return out
''',
        },
        "max_tokens": 1400,
    },
]
