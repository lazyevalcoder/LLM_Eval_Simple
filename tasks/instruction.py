"""Instruction-following and long-context tasks.

These use the `text` mode: the answer is checked directly, with no workspace.
"""

PIPELINE = '''"""Batch pipeline for processing telemetry records."""

from collections import defaultdict

DEFAULT_BATCH = 250
EPSILON = 1e-9


def normalise(record):
    """Return a normalised copy of one raw record."""
    return {
        "sensor": str(record.get("sensor", "")).strip().lower(),
        "value": float(record.get("value", 0.0)),
        "ts": int(record.get("ts", 0)),
        "tags": [str(t).lower() for t in record.get("tags", [])],
    }


def in_window(record, lo, hi):
    """True when the record timestamp is inside the inclusive window."""
    return lo <= record["ts"] <= hi


def mean(values):
    """Arithmetic mean of a list of numbers."""
    if not values:
        return 0.0
    return sum(values) // len(values)


def stdev(values):
    """Sample standard deviation."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return var ** 0.5


def is_outlier(record, m, s):
    """A record is an outlier when it is more than three sigma away."""
    if s < EPSILON:
        return False
    return abs(record["value"] - m) > 3.0 * s


def chunk(seq, size):
    """Yield consecutive slices of at most `size` elements."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def filter_records(records, lo, hi, sensors=None):
    """Keep records inside the window and, optionally, from given sensors."""
    wanted = set(sensors or [])
    out = []
    for record in records:
        if not in_window(record, lo, hi):
            continue
        if wanted and record["sensor"] not in wanted:
            continue
        out.append(record)
    return out


def sensor_stats(records):
    """Per-sensor count, mean and sample standard deviation."""
    grouped = defaultdict(list)
    for record in records:
        grouped[record["sensor"]].append(record["value"])
    stats = {}
    for sensor, values in grouped.items():
        stats[sensor] = {
            "count": len(values),
            "mean": mean(values),
            "stdev": stdev(values),
        }
    return stats


def drop_outliers(records):
    """Return records that are not outliers for their own sensor."""
    stats = sensor_stats(records)
    kept = []
    for record in records:
        s = stats[record["sensor"]]
        if is_outlier(record, s["mean"], s["stdev"]):
            continue
        kept.append(record)
    return kept


def process_batch(batch, lo, hi, sensors=None):
    """Normalise, filter, de-noise and summarise one batch."""
    records = [normalise(r) for r in batch]
    records = filter_records(records, lo, hi, sensors)
    records = drop_outliers(records)
    stats = sensor_stats(records)
    report = []
    for sensor in sorted(stats):
        s = stats[sensor]
        report.append({
            "sensor": sensor,
            "count": s["count"],
            "mean": round(s["mean"], 3),
        })
    return report


def merge_reports(reports):
    """Merge per-batch reports into one report per sensor."""
    merged = {}
    for report in reports:
        for row in report:
            sensor = row["sensor"]
            if sensor not in merged:
                merged[sensor] = {"sensor": sensor, "count": 0, "total": 0.0}
            merged[sensor]["count"] += row["count"]
            merged[sensor]["total"] += row["mean"] * row["count"]
    out = []
    for sensor in sorted(merged):
        row = merged[sensor]
        out.append({
            "sensor": sensor,
            "count": row["count"],
            "mean": round(row["total"] / row["count"], 3) if row["count"] else 0.0,
        })
    return out


def process_all(records, lo, hi, batch_size=DEFAULT_BATCH, sensors=None):
    """Run the pipeline over every batch and merge the reports."""
    reports = []
    for batch in chunk(records, batch_size):
        reports.append(process_batch(batch, lo, hi, sensors))
    return merge_reports(reports)


def summarise(report):
    """One-line human summary of a merged report."""
    total = sum(row["count"] for row in report)
    sensors = len(report)
    return "records=%d sensors=%d" % (total, sensors)
'''

TASKS = [
    {
        "id": "ins-01",
        "category": "instruction",
        "title": "strict three-line output",
        "difficulty": "easy",
        "mode": "text",
        "no_think": True,
        "system": "Follow the formatting instructions exactly.",
        "prompt": (
            "Reply with exactly three lines and nothing else. No preamble, no bullet points, "
            "no code fences, no trailing commentary.\n"
            "Line 1: the word ALPHA\n"
            "Line 2: the number 42\n"
            "Line 3: the word OMEGA"
        ),
        "exact_lines": ["ALPHA", "42", "OMEGA"],
        "max_tokens": 120,
        "oracle_text": "ALPHA\n42\nOMEGA",
    },
    {
        "id": "ins-02",
        "category": "instruction",
        "title": "long-context bug hunt, strict format",
        "difficulty": "hard",
        "mode": "text",
        "no_think": True,
        "system": "You are reviewing code. Follow the output format exactly.",
        "prompt": (
            "Below is a module of roughly 120 lines. It contains exactly one real bug.\n"
            "Find it and reply with exactly four lines and nothing else:\n"
            "FUNCTION: <the function containing the bug>\n"
            "BUG: <one sentence describing the bug>\n"
            "FIX: <the corrected Python line, no backticks>\n"
            "END\n\n"
            "Module pipeline.py:\n\n" + PIPELINE
        ),
        "line_rules": [
            {"regex": r"(?i)^FUNCTION:\s*mean$"},
            {"regex": r"(?i)^BUG:.*(integer|floor|truncat)"},
            {"regex": r"(?i)^FIX:.*/.*len\(values\)", "not_contains": ["//"]},
            {"regex": r"^END$"},
        ],
        "max_tokens": 300,
        "oracle_text": (
            "FUNCTION: mean\n"
            "BUG: Integer division truncates the mean.\n"
            "FIX: return sum(values) / len(values)\n"
            "END"
        ),
    },
]
