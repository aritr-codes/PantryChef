"""Every results/NAME.json link in the docs must point to a file that load_result accepts."""

import re
from pathlib import Path

import pytest

from pantrychef.eval.results import load_result

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\(((?:\.\./)?results/([A-Za-z0-9_.\-]+\.json))\)")
DOCS = [*sorted((ROOT / "docs").glob("*.md")), ROOT / "README.md"]


def links():
    return sorted({(d.name, m.group(2)) for d in DOCS for m in LINK.finditer(d.read_text("utf-8"))})


def test_link_pattern():
    assert LINK.findall("[a](../results/x_1.json) and [b](results/y.json) [c](results/z.csv)") == [
        ("../results/x_1.json", "x_1.json"),
        ("results/y.json", "y.json"),
    ]


def test_docs_link_to_results():
    assert links(), "no results links found; the pattern may be broken"


@pytest.mark.parametrize(("doc", "name"), links())
def test_link_resolves_and_validates(doc, name):
    path = ROOT / "results" / name
    assert path.is_file(), f"{doc} links to missing results/{name}"
    load_result(path)
