"""Pack builder, input allow-list and guard tests."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from pantrychef.engine import Pack, resolve_names
from pantrychef.ingredients.table import DEFAULT_TABLE_PATH, DEFAULT_WORDS_PATH, IngredientTable
from pantrychef.pack.allowlist import AllowlistError, sha256_file
from pantrychef.pack.build import BuildError, build_pack, check_source_url
from pantrychef.pack.guard import GuardViolation, guarded_build

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "tests" / "fixtures" / "wikibooks" / "pages.json"
REAL_SNAPSHOT = ROOT / "data" / "raw" / "wikibooks" / "snapshot.2026-11-03.jsonl.gz"


def _snapshot(path: Path, records: list[dict]) -> None:
    raw = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf8")
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(raw)


def _allowlist(
    tmp: Path, snapshot: Path, table: Path = DEFAULT_TABLE_PATH, words: Path = DEFAULT_WORDS_PATH
) -> Path:
    path = tmp / "allowlist.json"
    path.write_text(
        json.dumps(
            {
                "inputs": {
                    "snapshot": {
                        "path": str(snapshot),
                        "sha256": sha256_file(snapshot),
                        "retrieved_on": "2026-11-03",
                    },
                    "table": {"path": str(table), "sha256": sha256_file(table)},
                    "words": {"path": str(words), "sha256": sha256_file(words)},
                }
            }
        ),
        encoding="utf8",
    )
    return path


@pytest.fixture
def fixture_build(tmp_path):
    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    out = tmp_path / "out"
    manifest = build_pack(
        _allowlist(tmp_path, snap), out, repo_root=ROOT, commit="test", dirty=False
    )
    return out, manifest


def _load(path: Path):
    with gzip.open(path, "rt", encoding="utf8") as fh:
        return json.load(fh)


def test_build_writes_core_text_and_manifest(fixture_build):
    out, manifest = fixture_build
    assert {p.name for p in out.iterdir()} == {
        "core.v1.json.gz",
        "text.v1.json.gz",
        "manifest.v1.json",
    }
    assert manifest["counts"]["recipes"] == 4  # 4 of the 6 fixture pages are recipes
    core = _load(out / "core.v1.json.gz")
    assert core["info"]["commit"] == "test" and core["info"]["recipes"] == 4
    assert core["keys"]["salt"] == "salt"
    assert all(r["rev"] and r["page"].startswith("Cookbook:") for r in core["recipes"])


def test_core_carries_the_word_lists_for_the_typed_name_resolver(fixture_build):
    out, _ = fixture_build
    core = _load(out / "core.v1.json.gz")
    assert core["words"] == json.loads(DEFAULT_WORDS_PATH.read_text(encoding="utf8"))
    pack = Pack.from_core(core)
    assert resolve_names(pack, ["2 cups butter", "xylophone"]) == (["butter"], ["xylophone"])


def test_idf_is_log_one_plus_n_over_df(fixture_build):
    out, _ = fixture_build
    core = _load(out / "core.v1.json.gz")
    n = len(core["recipes"])
    df = {}
    for r in core["recipes"]:
        for i in {i for ln in r["lines"] for i in ln["o"]}:
            df[i] = df.get(i, 0) + 1
    idf = {i["id"]: i["idf"] for i in core["ingredients"]}
    assert df["butter"] >= 1
    for ing, d in df.items():
        assert idf[ing] == math.log(1 + n / d)
    assert idf["tahini"] == 0.0  # not in any fixture recipe


def test_text_pack_carries_attribution(fixture_build):
    out, _ = fixture_build
    text = _load(out / "text.v1.json.gz")["recipes"]["wb-3283"]
    assert text["url"] == "https://en.wikibooks.org/wiki/Cookbook:Apple_Cobbler"
    assert text["revision_id"] == 4587240 and text["licence"] == "CC BY-SA 4.0"
    assert len(text["steps"]) == 8 and "wording is unchanged" in text["changes"]


def test_manifest_lists_every_shipped_file_with_hash_size_licence(fixture_build):
    out, manifest = fixture_build
    shipped = {p.name for p in out.iterdir()} - {"manifest.v1.json"}
    assert {f["name"] for f in manifest["files"]} == shipped
    for f in manifest["files"]:
        data = (out / f["name"]).read_bytes()
        assert f["sha256"] == hashlib.sha256(data).hexdigest() and f["size"] == len(data)
        assert f["licence"] == "CC BY-SA 4.0"
    assert json.loads((out / "manifest.v1.json").read_text()) == manifest
    assert set(manifest["inputs"]) == {"snapshot", "table", "words"}


def test_build_is_deterministic(tmp_path):
    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    al = _allowlist(tmp_path, snap)
    a = build_pack(al, tmp_path / "a", repo_root=ROOT, commit="c", dirty=False)
    b = build_pack(al, tmp_path / "b", repo_root=ROOT, commit="c", dirty=False)
    assert a == b


def test_recipe_with_only_staple_lines_is_dropped(tmp_path):
    rec = {
        "page_id": 7,
        "title": "Cookbook:Salt Water",
        "revision_id": 1,
        "timestamp": "t",
        "wikitext": "==Ingredients==\n*1 cup water\n*1 tsp salt\n*pepper to taste\n",
    }
    ok = {
        **rec,
        "page_id": 8,
        "title": "Cookbook:Buttered Toast",
        "wikitext": "==Ingredients==\n*2 slices bread\n*butter\n",
    }
    snap = tmp_path / "s.jsonl.gz"
    _snapshot(snap, [rec, ok])
    manifest = build_pack(
        _allowlist(tmp_path, snap), tmp_path / "o", repo_root=ROOT, commit="c", dirty=False
    )
    assert manifest["counts"]["recipes"] == 1
    assert manifest["counts"]["dropped_no_required_line"] == 1


def test_changed_input_hash_fails_the_build(tmp_path):
    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    al = _allowlist(tmp_path, snap)
    _snapshot(snap, [])  # change the snapshot after it was pinned
    with pytest.raises(AllowlistError, match="hash changed"):
        build_pack(al, tmp_path / "o", repo_root=ROOT, commit="c", dirty=False)


def test_guard_blocks_reading_a_file_outside_the_allow_list(tmp_path):
    rogue = tmp_path / "vocab.json"  # outside the repo, like a stray copy of a research file
    rogue.write_text("[]")
    allowed = tmp_path / "ok.txt"
    allowed.write_text("ok")
    with guarded_build([allowed], tmp_path / "out", [ROOT / "pantrychef"]):
        assert allowed.read_text() == "ok"
        with pytest.raises(GuardViolation, match="outside the allow-list"):
            rogue.read_text()
        with pytest.raises(GuardViolation):
            rogue.read_bytes()
    assert rogue.read_text() == "[]"  # the guard is off again


def test_guard_blocks_repo_data_files(tmp_path):
    vocab = ROOT / "data" / "processed" / "vocab.json"
    with guarded_build([], tmp_path, [ROOT / "pantrychef"]), pytest.raises(GuardViolation):
        vocab.read_text()


def test_guard_blocks_writes_outside_the_output_folder(tmp_path):
    with guarded_build([], tmp_path / "out", [ROOT / "pantrychef"]):
        with pytest.raises(GuardViolation, match="write"):
            (tmp_path / "elsewhere.txt").write_text("x")
        (tmp_path / "out").mkdir()
        with open(tmp_path / "out" / "fine.txt", "w") as fh:
            fh.write("x")


def test_guard_blocks_processes_and_sockets(tmp_path):
    with guarded_build([], tmp_path, [ROOT / "pantrychef"]):
        with pytest.raises(GuardViolation):
            subprocess.run([sys.executable, "-c", "pass"], check=False)
        with pytest.raises(GuardViolation):
            socket.create_connection(("127.0.0.1", 9), timeout=0.1)


def test_a_builder_that_reads_a_stray_file_fails(tmp_path, monkeypatch):
    """A change to the build code that reads another data file must fail the build."""
    import pantrychef.pack.build as build_mod

    stray = tmp_path / "vocab.json"
    stray.write_text("[]")
    real = build_mod.resolve_lines

    def sneaky(text, table):
        stray.read_text()
        return real(text, table)

    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    al = _allowlist(tmp_path, snap)
    monkeypatch.setattr(build_mod, "resolve_lines", sneaky)
    with pytest.raises(GuardViolation):
        build_pack(al, tmp_path / "o", repo_root=ROOT, commit="c", dirty=False)


def test_guard_allows_bytecode_in_pycache_but_not_other_pyc_files(tmp_path):
    with guarded_build([], tmp_path / "out", [ROOT / "pantrychef"]):
        with pytest.raises(GuardViolation):
            (tmp_path / "evil.pyc").write_bytes(b"x")
        with pytest.raises(GuardViolation):
            (tmp_path / "__pycache__x" / "m.pyc").parent.mkdir()
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    with guarded_build([], tmp_path / "out", [ROOT / "pantrychef"]):
        (cache / "m.cpython-311.pyc.123").write_bytes(b"x")  # what Python writes on import


def test_output_folder_may_not_contain_inputs_or_code(tmp_path):
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    with (
        pytest.raises(GuardViolation, match="would contain"),
        guarded_build([inp], tmp_path, [ROOT / "pantrychef"]),
    ):
        pass
    with (
        pytest.raises(GuardViolation, match="would contain"),
        guarded_build([], ROOT, [ROOT / "pantrychef"]),
    ):
        pass


def test_guard_blocks_deleting_and_renaming_outside_the_output_folder(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("x")
    with guarded_build([], tmp_path / "out", [ROOT / "pantrychef"]):
        with pytest.raises(GuardViolation, match="change files"):
            victim.unlink()
        with pytest.raises(GuardViolation, match="change files"):
            victim.rename(tmp_path / "moved.txt")
    assert victim.exists()


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://en.wikibooks.org/wiki/X",
        "https://en.wikipedia.org/wiki/X",
        "https://en.wikibooks.org.evil.example/wiki/X",
        "https://en.wikibooks.org@evil.example/wiki/X",
        "//en.wikibooks.org/wiki/X",
    ],
)
def test_source_url_must_be_https_wikibooks(url):
    with pytest.raises(BuildError):
        check_source_url(url)


def test_source_url_accepts_wikibooks():
    check_source_url("https://en.wikibooks.org/wiki/Cookbook:Apple_Cobbler")
    check_source_url("https://en.wikibooks.org/w/index.php?oldid=4587240")


@pytest.mark.skipif(not REAL_SNAPSHOT.exists(), reason="needs the local Wikibooks snapshot")
def test_real_pack_core_is_under_3_mb(tmp_path):
    al = ROOT / "pantrychef" / "pack" / "allowlist.json"
    manifest = build_pack(al, tmp_path, repo_root=ROOT, commit="local", dirty=False)
    core = next(f for f in manifest["files"] if f["name"].startswith("core."))
    assert core["size"] < 3 * 1024 * 1024
    assert manifest["counts"]["recipes"] > 3000


def test_build_uses_the_listed_words_file_and_reads_nothing_else(tmp_path, monkeypatch):
    """The build passes the allow-listed words in. The default words are never opened."""
    import pantrychef.pack.build as build_mod

    seen = []
    real = IngredientTable.from_text.__func__

    def spy(cls, text, words_json=None):
        seen.append(words_json)
        return real(cls, text, words_json)

    monkeypatch.setattr(build_mod.IngredientTable, "from_text", classmethod(spy))
    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    manifest = build_pack(
        _allowlist(tmp_path, snap), tmp_path / "o", repo_root=ROOT, commit="c", dirty=False
    )
    assert seen == [DEFAULT_WORDS_PATH.read_text(encoding="utf8")]
    assert manifest["inputs"]["words"]["sha256"] == sha256_file(DEFAULT_WORDS_PATH)


def test_from_text_without_words_opens_no_file_in_a_guarded_build(tmp_path):
    csv_text = "id,name,synonyms,staple,provenance\na,apple,,0,hand\n"
    with guarded_build([], tmp_path / "out", [ROOT / "pantrychef"]):
        assert IngredientTable.from_text(csv_text).words.staple_cue == {"salt"}
