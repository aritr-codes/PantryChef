from pathlib import Path

import pytest

from pantrychef.eval.results import load_result

FILES = sorted((Path(__file__).resolve().parents[2] / "results").glob("m1_latency_*.json"))
FILES = [p for p in FILES if p.name != "m1_latency_device.json"]  # new in M2: a different shape


def test_four_files_found():
    assert len(FILES) == 4


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_numbers_match_original(path):
    d = load_result(path)
    raw = d["raw"]
    assert d["label"] == "MEASURED"
    assert (d["commit"], d["dirty"], d["seed"]) == (raw["commit"], raw["dirty"], raw["seed"])
    by_size = raw["metrics"]["bySize"]
    assert len(d["metrics"]) == 3 * len(by_size)
    for m in d["metrics"]:
        s = by_size[str(m["group"]["pantry_size"])]
        key = {"latency_p50_ms": "p50", "latency_p95_ms": "p95", "latency_max_ms": "max"}[m["name"]]
        assert m["value"] == s[key] and m["n"] == s["n"]
