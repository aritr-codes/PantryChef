"""Rule baselines on RecipeNLG at full scale (M2, Lane D): random, overlap, idf_flat.

Research only (ADR 0003). Nothing here ships and the output holds no recipe text.

Task (plan section 3, adapted): RecipeNLG has canonical ingredient sets and no groups.
Gold = recipe with n >= 3 ingredients. Mask m = (n + 2) // 4 ingredients with
``random.Random(f"{seed}:{recipe_id}:{draw}")``. Pantry = unmasked ingredients + d distractors
(uniform or popularity, never an ingredient of the gold recipe, no repeats). Three draws per gold.
Every arm ranks the SAME exact candidate set: all recipes sharing at least one pantry ingredient.

* overlap  : order (-have, total, id)
* idf_flat : score = sum idf(satisfied) / sqrt(sum idf(all)), idf = log(1 + N / df);
             order (-score, total, id)
* random   : a seeded shuffle. The gold rank of a uniform shuffle is uniform on 1..C, so the
             kernel draws that rank directly from ``random.Random("random-arm:...")``. This is the
             same distribution and avoids shuffling up to 1M candidates per pantry.

``id`` is the row position in the cleaned file (recipe ids are ``r<position>`` there).
Memory: integer ids, CSR and inverted arrays, numpy scoring. See kaggle/rule_baselines/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
import sys
import time
from array import array
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from itertools import accumulate
from pathlib import Path
from typing import Any

import numpy as np

from pantrychef.eval.pantries import mask_count
from pantrychef.eval.stats import paired_cluster_bootstrap

K = 10
ARM_NAMES = ("random", "overlap", "idf_flat")
FEATURES = {"random": [], "overlap": ["have", "total"], "idf_flat": ["idf", "have", "total"]}
SAMPLERS = ("uniform", "popularity")
PAIRS = (("overlap", "random"), ("idf_flat", "overlap"))
METRIC_NAMES = ("recall_at_10", "mrr_at_10")
MIN_INGREDIENTS = 3


# ---------------------------------------------------------------- corpus input


def _records(corpus: Iterable[Any] | str | Path) -> Iterator[tuple[str, list[str]]]:
    """Yield ``(recipe_id, canonical)``. Accepts a JSONL path or dicts/objects."""
    if isinstance(corpus, (str, Path)):
        with open(corpus, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    yield d["recipe_id"], d.get("canonical", [])
        return
    for r in corpus:
        if isinstance(r, dict):
            yield r["recipe_id"], r.get("canonical", [])
        else:
            yield r.recipe_id, r.canonical


class Index:
    """CSR (recipe to ingredients) and inverted (ingredient to recipes) arrays of int ids."""

    def __init__(self, corpus: Iterable[Any] | str | Path):
        vocab: dict[str, int] = {}
        indptr = array("q", [0])
        flat = array("i")
        self.recipe_ids: list[str] = []
        for rid, canon in _records(corpus):
            ids = sorted({vocab.setdefault(c, len(vocab)) for c in canon})
            flat.extend(ids)
            indptr.append(len(flat))
            self.recipe_ids.append(rid)
        self.n = len(self.recipe_ids)
        self.v = len(vocab)
        self.indptr = np.frombuffer(indptr, dtype=np.int64)
        self.flat = np.frombuffer(flat, dtype=np.int32)
        del vocab
        self.total = np.diff(self.indptr).astype(np.int32)
        owner = np.repeat(np.arange(self.n, dtype=np.int32), self.total)
        order = np.argsort(self.flat, kind="stable")  # recipes stay ascending inside a posting list
        self.post = owner[order]
        self.ing_ptr = np.concatenate(([0], np.cumsum(np.bincount(self.flat, minlength=self.v))))
        self.df = np.diff(self.ing_ptr)
        self.idf = np.log1p(self.n / np.maximum(self.df, 1))
        # sum of idf in ascending ingredient id order: equal sets give equal bits
        self.den = np.bincount(owner, weights=self.idf[self.flat], minlength=self.n)
        del owner, order

    def ingredients(self, r: int) -> list[int]:
        return self.flat[self.indptr[r] : self.indptr[r + 1]].tolist()

    def _candidates(self, pantry: Iterable[int]):
        """Return ``(u, have, score)`` for every recipe sharing an ingredient with the pantry."""
        ings = sorted(set(pantry))
        parts = [self.post[self.ing_ptr[i] : self.ing_ptr[i + 1]] for i in ings]
        rec = np.concatenate(parts) if parts else np.empty(0, dtype=np.int32)
        w = np.repeat(self.idf[ings], [len(p) for p in parts])
        have = np.bincount(rec, minlength=self.n)
        num = np.bincount(rec, weights=w, minlength=self.n)
        u = np.flatnonzero(have)
        return u, have[u], num[u] / np.sqrt(self.den[u])

    def order(self, pantry: Iterable[int], arm: str) -> list[int]:
        """Full candidate order for ``overlap`` or ``idf_flat`` (used by tests; slow path)."""
        u, h, s = self._candidates(pantry)
        t = self.total[u]
        key = -h if arm == "overlap" else -s
        return u[np.lexsort((u, t, key))].tolist()

    def ranks(self, pantry: Iterable[int], gold: int) -> tuple[int, int, int]:
        """``(overlap_rank, idf_flat_rank, n_candidates)`` of ``gold``. Ranks start at 1.

        Rank = 1 + number of candidates that sort strictly before gold. No sorting is needed.
        """
        u, h, s = self._candidates(pantry)
        t = self.total[u]
        g = int(np.searchsorted(u, gold))
        if g >= len(u) or u[g] != gold:
            raise ValueError("gold is not in its own candidate set")
        hg, tg, sg = h[g], t[g], s[g]
        before_t = (t < tg) | ((t == tg) & (u < gold))
        ov = int(np.count_nonzero((h > hg) | ((h == hg) & before_t)))
        idf = int(np.count_nonzero((s > sg) | ((s == sg) & before_t)))
        return ov + 1, idf + 1, len(u)


# ---------------------------------------------------------------- pantries


class Distractors:
    """Sequential draws without repeats and never from the gold ingredients (rejection)."""

    def __init__(self, index: Index):
        self.v = index.v
        self.cum = list(accumulate(index.df.tolist()))

    def draw(self, sampler: str, rng: random.Random, exclude: set[int], d: int) -> list[int]:
        if d > self.v - len(exclude):
            raise ValueError(f"cannot draw {d} distractors from {self.v - len(exclude)} ids")
        taken = set(exclude)
        out: list[int] = []
        while len(out) < d:
            if sampler == "uniform":
                x = rng.randrange(self.v)
            elif sampler == "popularity":
                x = bisect_right(self.cum, rng.random() * self.cum[-1])
            else:
                raise ValueError(f"unknown sampler {sampler!r}")
            if x not in taken:
                taken.add(x)
                out.append(x)
        return out


def mask_pantry(
    index: Index, gold: int, seed: int, draw: int
) -> tuple[list[int], list[int], random.Random]:
    """``(kept, masked, rng)`` for one gold and draw. The rng continues for distractors."""
    ings = index.ingredients(gold)
    rng = random.Random(f"{seed}:{index.recipe_ids[gold]}:{draw}")
    masked_idx = set(rng.sample(range(len(ings)), mask_count(len(ings))))
    kept = [x for i, x in enumerate(ings) if i not in masked_idx]
    masked = [x for i, x in enumerate(ings) if i in masked_idx]
    return kept, masked, rng


def select_queries(index: Index, n_queries: int, seed: int) -> list[int]:
    """First ``n_queries`` eligible recipes by sha256(f"{seed}:{recipe_id}") order."""
    elig = np.flatnonzero(index.total >= MIN_INGREDIENTS)
    keys = np.fromiter(
        (
            int.from_bytes(
                hashlib.sha256(f"{seed}:{index.recipe_ids[r]}".encode()).digest()[:8], "big"
            )
            for r in elig
        ),
        dtype=np.uint64,
        count=len(elig),
    )
    top = elig[np.lexsort((elig, keys))[:n_queries]]
    # exact order inside the chosen set: full hex digest (the 8-byte prefix only picks the set)
    return sorted(
        top.tolist(),
        key=lambda r: hashlib.sha256(f"{seed}:{index.recipe_ids[r]}".encode()).hexdigest(),
    )


def _sha_lines(items: list[str]) -> str:
    return hashlib.sha256(("\n".join(items) + "\n").encode()).hexdigest()


# ---------------------------------------------------------------- run


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def run(
    corpus: Iterable[Any] | str | Path,
    n_queries: int = 20_000,
    seed: int = 42,
    samplers: list[str] | None = None,
    d_values: list[int] | None = None,
    draws: int = 3,
    resamples: int = 10_000,
    log: bool = False,
) -> dict[str, Any]:
    """Run the baselines. Return the result body (metrics, comparisons, arms, config, raw...)."""
    t0 = time.time()
    samplers = list(samplers) if samplers else list(SAMPLERS)
    d_values = list(d_values) if d_values is not None else [0, 3, 6]
    index = Index(corpus)
    queries = select_queries(index, n_queries, seed)
    n_dev = len(queries) // 2
    split_of = {g: ("dev" if i < n_dev else "test") for i, g in enumerate(queries)}
    dist = Distractors(index)
    configs = [("none", 0)] if 0 in d_values else []
    configs += [(s, d) for d in d_values if d > 0 for s in samplers]
    # vals[(cfg, split, arm, metric)] = per-pantry values; clusters[(cfg, split)] = gold ids
    vals: dict[tuple, list[float]] = {}
    clusters: dict[tuple, list[str]] = {}
    cand_sum: dict[tuple, int] = {}
    for qi, gold in enumerate(queries):
        gid, split = index.recipe_ids[gold], split_of[gold]
        gold_set = set(index.ingredients(gold))
        for draw in range(draws):
            kept, masked, rng0 = mask_pantry(index, gold, seed, draw)
            state = rng0.getstate()
            for cfg in configs:
                sampler, d = cfg
                rng = random.Random()
                rng.setstate(state)  # every config continues the same stream after the mask
                extra = dist.draw(sampler, rng, gold_set, d) if d else []
                assert not (set(extra) & gold_set), "distractor from gold recipe"
                ov, idf, c = index.ranks(kept + extra, gold)
                rr = random.Random(f"random-arm:{seed}:{gid}:{draw}").randrange(c) + 1
                clusters.setdefault((cfg, split), []).append(gid)
                cand_sum[(cfg, split)] = cand_sum.get((cfg, split), 0) + c
                for arm, rank in (("random", rr), ("overlap", ov), ("idf_flat", idf)):
                    vals.setdefault((cfg, split, arm, "recall_at_10"), []).append(
                        1.0 if rank <= K else 0.0
                    )
                    vals.setdefault((cfg, split, arm, "mrr_at_10"), []).append(
                        1.0 / rank if rank <= K else 0.0
                    )
        if log and (qi + 1) % 500 == 0:
            print(
                f"[{time.time() - t0:.0f}s] {qi + 1}/{len(queries)} golds",
                file=sys.stderr,
                flush=True,
            )

    metrics: list[dict] = []
    comparisons: list[dict] = []
    dev: list[dict] = []
    for cfg in configs:
        group = {"sampler": cfg[0], "d": cfg[1]}
        for split in ("dev", "test"):
            cl = clusters.get((cfg, split))
            if not cl:
                continue
            n = len(cl)
            for arm in ARM_NAMES:
                for name in METRIC_NAMES:
                    row = {
                        "name": name,
                        "arm": arm,
                        "split": split,
                        "group": group,
                        "n": n,
                        "value": _mean(vals[(cfg, split, arm, name)]),
                    }
                    # dev is for debugging only: it stays out of the reported metrics
                    (metrics if split == "test" else dev).append(row)
            if split != "test":
                continue
            for a, b in PAIRS:
                for name in METRIC_NAMES:
                    iv = paired_cluster_bootstrap(
                        vals[(cfg, split, a, name)],
                        vals[(cfg, split, b, name)],
                        cl,
                        resamples=resamples,
                        seed=seed,
                    )
                    comparisons.append(
                        {
                            "metric": name,
                            "a": a,
                            "b": b,
                            "split": split,
                            "group": group,
                            "n": n,
                            "diff": iv.mean,
                            "ci": {
                                "lo": iv.lo,
                                "hi": iv.hi,
                                "level": iv.level,
                                "method": iv.method,
                                "n_clusters": iv.n_clusters,
                            },
                        }
                    )
    qids = [index.recipe_ids[g] for g in queries]
    return {
        "metrics": metrics,
        "comparisons": comparisons,
        "arms": [{"name": a, "features_used": FEATURES[a]} for a in ARM_NAMES],
        "config": {
            "samplers": samplers,
            "d_values": d_values,
            "draws": draws,
            "k": K,
            "resamples": resamples,
            "n_queries": len(queries),
            "n_queries_requested": n_queries,
            "mask": "m = (n + 2) // 4",
            "min_ingredients": MIN_INGREDIENTS,
            "candidate_set": "all recipes sharing at least one pantry ingredient (exact)",
            "random_arm": "gold rank drawn uniform on 1..C (equals a seeded shuffle)",
            "tie_break_id": "row position in the cleaned file",
        },
        "seed": seed,
        "raw": {
            "n_recipes": index.n,
            "n_vocab": index.v,
            "n_eligible": int(np.count_nonzero(index.total >= MIN_INGREDIENTS)),
            "n_dev": n_dev,
            "n_test": len(queries) - n_dev,
            "query_ids_sha256": _sha_lines(qids),
            "mean_candidates_test": {
                f"sampler={c[0]},d={c[1]}": cand_sum[(c, "test")] / len(clusters[(c, "test")])
                for c in configs
                if (c, "test") in clusters
            },
            "dev_metrics_debug_only": dev,
            "seconds": round(time.time() - t0, 1),
        },
    }


# ---------------------------------------------------------------- cleaning and CLI


def sha256_file(path: str | Path, chunk: int = 1 << 24) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def clean_csv(csv_path: str | Path, out_jsonl: str | Path, min_count: int = 5) -> int:
    """Two passes as in scripts/download_data.py: vocabulary, then clean. Returns recipe count."""
    from pantrychef.data.clean import clean_recipes
    from pantrychef.data.loaders import load_recipenlg
    from pantrychef.data.store import save_recipes
    from pantrychef.ingredients.vocab import build_vocabulary

    vocab = build_vocabulary(load_recipenlg(csv_path), min_count=min_count)
    n = 0

    def counted():
        nonlocal n
        for r in clean_recipes(load_recipenlg(csv_path), vocab):
            n += 1
            yield r

    save_recipes(counted(), out_jsonl)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pantrychef.eval.rule_baselines_main")
    ap.add_argument("--corpus", required=True, help="cleaned recipes JSONL")
    ap.add_argument("--out", required=True, help="results JSON path")
    ap.add_argument("--n-queries", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resamples", type=int, default=10_000)
    ap.add_argument("--csv-sha256", default="", help="sha256 of the source CSV (the fingerprint)")
    ap.add_argument("--commit", default="", help="40-hex commit when no git checkout exists")
    ap.add_argument(
        "--tree",
        choices=["clean", "dirty"],
        help="state of the build tree at --commit, from the build host (required with --commit)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if bool(args.commit) != bool(args.tree):
        ap.error("--commit and --tree go together")
    from pantrychef.eval import results

    body = run(
        args.corpus,
        n_queries=args.n_queries,
        seed=args.seed,
        resamples=args.resamples,
        log=not args.quiet,
    )
    body["raw"]["cleaned_sha256"] = sha256_file(args.corpus)
    body["raw"]["csv_sha256"] = args.csv_sha256
    body["corpus_fingerprint"] = args.csv_sha256 or body["raw"]["cleaned_sha256"]
    doc = {
        "label": "MEASURED",
        "what": "M2 rule baselines on RecipeNLG (random, overlap, idf_flat); research only",
        "command": "python -m pantrychef.eval.rule_baselines_main "
        + shlex.join(argv if argv is not None else sys.argv[1:]),
        **body,
    }
    if args.commit:  # no git checkout (Kaggle): the caller states the commit the wheel was built at
        body["raw"]["commit_source"] = "supplied by caller from the build host, not verified here"
        dirty = args.tree == "dirty"
        paths = ["(build host tree was dirty; paths not recorded)"] if dirty else []
        real = results.git_facts
        results.git_facts = lambda root, exclude=(): (args.commit, dirty, paths)  # type: ignore[assignment]
        try:
            results.write_result(Path(args.out), doc)
        finally:
            results.git_facts = real
    else:
        results.write_result(Path(args.out), doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
