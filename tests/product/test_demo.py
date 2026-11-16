"""The product-value demonstration stays reproducible and its headline numbers stay honest."""

from __future__ import annotations

import json

import demo


def test_demo_numbers(tmp_path):
    demo.sys.argv = ["demo.py", str(tmp_path)]
    assert demo.main() == 0
    data = json.loads((tmp_path / "product-value-demo.json").read_text(encoding="utf-8"))
    by = {r["fixture"]: r for r in data["results"]}
    for r in by.values():
        assert r["detected_exactly"] == r["planted_classes"] and not r["missed"] and not r["baseline_errors"]
        # Anonimizer must carry nearly every planted class into its output; the plain generator almost none.
        assert r["represented_in_anonimizer_output"] >= r["planted_classes"] - 2
        assert r["present_in_baseline_output"] <= 2
    text = (tmp_path / "product-value-demo.md").read_text(encoding="utf-8")
    assert "does not show" in text and "not a certification" in text
    for canary in ("Wolfhaven77", "CANARY-NOTE-7731", "ZZTOP-SECRET-4242", "Quuxinator", "pending review", "douze"):
        assert canary not in text
