import { useEffect, useRef, useState } from "preact/hooks";
import { type Engine, recipe } from "./engine";
import { historyUrl, safeWikibooksUrl } from "./links";
import { type LineStatus, STATUS_LABEL, lineStatus } from "./status";
import type { RecipeDetail } from "./types";

interface Props {
  engine: Engine;
  recipeId: string;
  pantry: string[];
  staples: string[];
  onBack: () => void;
}

// Plain-text markers, so the status never depends on colour or on an icon.
const MARK: Record<LineStatus, string> = {
  have: "[x]",
  missing: "[ ]",
  assumed: "(~)",
  optional: "[-]",
  check: "[?]",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function RecipeScreen({ engine, recipeId, pantry, staples, onBack }: Props) {
  const [detail, setDetail] = useState<RecipeDetail | null | undefined>(undefined);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    setDetail(undefined);
    recipe(recipeId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [recipeId]);
  // The heading exists only once the text has loaded, so focus moves here and not in the App.
  useEffect(() => {
    if (detail) heading.current?.focus();
  }, [detail]);

  const back = (
    <button type="button" class="linkbtn" onClick={onBack}>
      ← Back to results
    </button>
  );
  if (detail === undefined) {
    return (
      <section class="slip-wide wrapslip">
        <div class="slip">
          {back}
          <p role="status">Loading recipe…</p>
        </div>
      </section>
    );
  }
  if (detail === null) {
    return (
      <section class="slip-wide wrapslip">
        <div class="slip">
          {back}
          <p role="alert">This recipe did not load.</p>
        </div>
      </section>
    );
  }
  const have = new Set(pantry);
  const stapleSet = new Set(staples);
  const src = detail.source;
  const page = safeWikibooksUrl(src.url);
  const rev = safeWikibooksUrl(src.revision_url);
  const history = historyUrl(src.url);
  const meta = [detail.category, detail.time, detail.servings && `Serves ${detail.servings}`].filter(Boolean);

  const rows = detail.lines.map((ln) => ({ ln, status: lineStatus(ln, have, stapleSet) }));
  const missing = [
    ...new Set(rows.filter((r) => r.status === "missing").map((r) => r.ln.o.map((o) => engine.name(o)).join(" or "))),
  ];
  const check = rows.filter((r) => r.status === "check").length;
  const said =
    (missing.length ? `Missing: ${missing.join(", ")}.` : "Nothing is missing.") +
    (check ? ` ${plural(check, "line needs", "lines need")} a check by hand.` : "");

  return (
    <article class="slip-wide wrapslip" aria-labelledby="recipe-h">
      <div class="slip">
        {back}
        <h2 class="big" id="recipe-h" tabIndex={-1} ref={heading} data-focus-heading>{detail.title}</h2>
        {meta.length > 0 && <p class="counts dim">{meta.join(" | ")}</p>}
        <p class="mono said">{said}</p>
        <hr class="hr" />
        <h3 class="label">Ingredients</h3>
        <ul class="lines">
          {rows.map(({ ln, status }, i) => (
            <li key={i} class={`line line-${status}`}>
              <span class="box" aria-hidden="true">{MARK[status]}</span>
              <span class="ltext">{status === "missing" ? <mark class="need">{ln.t}</mark> : ln.t}</span>
              <span class="w">{STATUS_LABEL[status]}</span>
            </li>
          ))}
        </ul>
        <hr class="hr" />
        <h3 class="label">Steps</h3>
        <ol class="steps">
          {detail.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
        <hr class="hr solid" />
        <footer class="attribution">
          <p>
            From the Wikibooks Cookbook:{" "}
            {page ? (
              <a href={page} target="_blank" rel="noopener noreferrer">
                {detail.title} (new tab)
              </a>
            ) : (
              detail.title
            )}
            .
          </p>
          <p>
            Revision{" "}
            {rev ? (
              <a href={rev} target="_blank" rel="noopener noreferrer">
                {src.revision_id}
              </a>
            ) : (
              src.revision_id
            )}
            , retrieved {src.retrieved_on}. Licence: {src.licence}
            {src.licence.startsWith("CC BY-SA") && (
              <>
                {" "}
                (
                <a
                  href="https://creativecommons.org/licenses/by-sa/4.0/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  licence text
                </a>
                )
              </>
            )}
            .{" "}
            {history && (
              <>
                Authors: see the{" "}
                <a href={history} target="_blank" rel="noopener noreferrer">
                  page history
                </a>
                .{" "}
              </>
            )}
            {src.changes}
          </p>
        </footer>
      </div>
    </article>
  );
}
