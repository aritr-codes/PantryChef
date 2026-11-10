import { useEffect, useRef, useState } from "preact/hooks";
import { Icon } from "./Icon";
import { type Engine, recipe } from "./engine";
import { historyUrl, safeWikibooksUrl } from "./links";
import { type LineStatus, STATUS_LABEL, lineStatus } from "./status";
import type { CoreLine, RecipeDetail } from "./types";

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

function andList(items: string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : (items[0] ?? "");
}

/** The ingredient a line stands for, for its icon: the one you have, the staple, or the first choice. */
function iconName(ln: CoreLine, status: LineStatus, pantry: ReadonlySet<string>, staples: ReadonlySet<string>, name: (id: string) => string) {
  if (status === "optional" || status === "check") return "";
  const id = (status === "have" ? ln.o.find((o) => pantry.has(o)) : status === "assumed" ? ln.o.find((o) => staples.has(o)) : ln.o[0]) ?? ln.o[0];
  return id ? name(id) : "";
}

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
    <button type="button" class="btn back" onClick={onBack}>
      ← Back to results
    </button>
  );
  if (detail === undefined) {
    return (
      <section id="answer" tabIndex={-1} class="wrap recipe-wrap" aria-label="Recipe">
        <div class="slip">
          {back}
          <p role="status">Loading recipe…</p>
        </div>
      </section>
    );
  }
  if (detail === null) {
    return (
      <section id="answer" tabIndex={-1} class="wrap recipe-wrap" aria-label="Recipe">
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
  const missing = [...new Set(rows.filter((r) => r.status === "missing").map((r) => r.ln.o.map((o) => engine.name(o)).join(" or ")))];
  const check = rows.filter((r) => r.status === "check").length;
  const said =
    (missing.length ? `You need ${andList(missing)}. You have the rest.` : "You have everything. You can start now.") +
    (check ? ` ${plural(check, "line needs", "lines need")} a check by hand.` : "");

  return (
    <article id="answer" tabIndex={-1} class="wrap recipe-wrap" aria-labelledby="recipe-h">
      <div class="slip">
        {back}
        {meta.length > 0 && <p class="kicker">{meta.join(" | ")}</p>}
        <h2 class="recipe-title" id="recipe-h" tabIndex={-1} ref={heading} data-focus-heading>{detail.title}</h2>
        <p class="said">{said}</p>
        <h3 class="kicker section">Ingredients</h3>
        <ul class="checks lines" role="list">
          {rows.map(({ ln, status }, i) => (
            <li key={i} class={`line line-${status} ${status === "have" ? "have-it" : status === "missing" ? "need-it" : ""}`}>
              <span class="mk" aria-hidden="true">{MARK[status]}</span>
              <Icon name={iconName(ln, status, have, stapleSet, (id) => engine.name(id))} />
              {status === "missing" ? <b class="ltext">{ln.t}</b> : <span class="ltext">{ln.t}</span>}
              <span class="st">{STATUS_LABEL[status]}</span>
            </li>
          ))}
        </ul>
        <h3 class="kicker section">Steps</h3>
        <ol class="steps" role="list">
          {detail.steps.map((s, i) => (
            <li key={i}>
              <span>{s}</span>
            </li>
          ))}
        </ol>
        <footer class="attribution src">
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
