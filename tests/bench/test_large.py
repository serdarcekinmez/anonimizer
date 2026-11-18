"""Large-file check (opt-in: pytest --runslow). Two million rows, one text value at 97.5 %."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

BUILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from build_fixtures import build_customers
truth = build_customers(sys.argv[2] + "/big.csv", n_rows=int(sys.argv[3]), seed=11)
planted = [a["rows"] for a in truth["anomalies"] if a["column"] == "balance" and a["class"] == "type.text_in_number"]
print(json.dumps({"planted_rows": planted}))
"""

# The pipeline runs in its own process so that its peak memory is not mixed with the builder's.
RUN = r"""
import json, os, resource, sys, time
from anonimizer.pipeline import run
path = sys.argv[1] + "/big.csv"
t0 = time.time()
res = run(path, policy_id="internal-dev", rows=100, seed=1, out_dir=sys.argv[1] + "/out", private_dir=sys.argv[1] + "/priv")
t_run = time.time() - t0
private = json.load(open(sys.argv[1] + "/priv/source_profile.PRIVATE.json"))
rows = [e["_private"]["rows"] for c in private["tables"][0]["columns"] if c["name"] == "balance"
        for e in c["exceptions"] if e["class"] == "type.text_in_number"]
print(json.dumps({"run_s": round(t_run, 1), "file_mb": os.path.getsize(path) // 2**20,
                  "rss_peak_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
                  "found_rows": rows, "status": res.assessment["assessment_status"],
                  "covered": res.coverage["tables"][0]["scenarios_covered"], "total": res.coverage["tables"][0]["scenarios_total"]}))
"""


@pytest.mark.slow
def test_two_million_rows(tmp_path):
    import os

    fixtures = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
    built = subprocess.run([sys.executable, "-c", BUILD, fixtures, str(tmp_path), "2000000"], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr[-2000:]
    planted = json.loads(built.stdout.strip().splitlines()[-1])["planted_rows"]
    out = subprocess.run([sys.executable, "-c", RUN, str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    m = json.loads(out.stdout.strip().splitlines()[-1])
    print("large-file measurement:", m)
    assert m["found_rows"] == planted == [[1950002]]
    assert m["status"] == "passed" and m["covered"] == m["total"]
    assert m["rss_peak_mb"] < 1024
    assert m["run_s"] < 900
