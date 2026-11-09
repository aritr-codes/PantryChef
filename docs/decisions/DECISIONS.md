# Architecture Decision Records (ADRs)

Each non-trivial decision gets its own numbered file capturing **context,
options, decision, and consequences** — recorded *at decision time*, not
retrofitted. This is where tradeoffs live.

Copy [`0000-template.md`](0000-template.md) for new ADRs.

## Index

| # | Title | Status |
| - | ----- | ------ |
| [0001](0001-monorepo-and-tooling.md) | Monorepo, uv/ruff/pytest (Hydra and MLflow removed in M0) | Accepted, amended |
| [0002](0002-no-llm-substitution.md) | No-LLM core: embeddings + graph for substitution | Accepted |
| [0003](0003-licence-clean-recipe-corpus.md) | Licence-clean recipe corpus for the public app | Accepted |
| [0004](0004-static-first-browser-engine.md) | Static-first app with a browser engine | Accepted |
| [0005](0005-honest-claims-and-eval-reset.md) | Honest claims and an evaluation reset | Accepted |
| [0006](0006-hybrid-graph-knowledge-base.md) | Hybrid: a graph knowledge base with ML on top | Rejected on 2026-11-09 by the M3 spike rule (narrow scope: see the ADR) |

_Update this table whenever an ADR is added or its status changes
(Proposed → Accepted → Superseded)._
