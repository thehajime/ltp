#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Require complete syscall coverage and only PASS/TCONF results."""
import collections
import json
import shlex
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    expected = {
        fields[0]
        for line in source
        if (fields := shlex.split(line, comments=True))
    }
with open(sys.argv[2], encoding="utf-8") as source:
    report = json.load(source)
results = report["results"]
actual = collections.Counter(result["test_fqn"] for result in results)
missing = expected - actual.keys()
extra = actual.keys() - expected
duplicates = [name for name, count in actual.items() if count != 1]
bad = [r["test_fqn"] for r in results if r["status"] not in ("pass", "conf")]
stats = report["stats"]
print(json.dumps({"tests": len(results), **stats}, indent=2))
for label, names in (("missing", missing), ("unexpected", extra),
                     ("duplicate", duplicates), ("unsuccessful", bad)):
    if names:
        print(f"{label}: {', '.join(sorted(names))}", file=sys.stderr)
sys.exit(bool(missing or extra or duplicates or bad or not expected or
              any(stats.get(key, 0) for key in ("failed", "broken", "warnings"))))
