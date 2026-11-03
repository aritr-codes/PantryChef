import { useEffect, useState } from "preact/hooks";
import { type Engine, recipe } from "./engine";
import { historyUrl, safeWikibooksUrl } from "./links";
import { STATUS_LABEL, lineStatus } from "./status";
import type { RecipeDetail } from "./types";

interface Props {
  engine: Engine;
  recipeId: string;
  pantry: string[];
  staples: string[];
  onBack: () => void;
}

export function RecipeScreen({ recipeId, pantry, staples, onBack }: Props) {
  const [detail, setDetail] = useState<RecipeDetail | null | undefined>(undefined);
  useEffect(() => {
    setDetail(undefined);
    recipe(recipeId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [recipeId]);

  if (detail === undefined) return <p role="status">Loading recipe…</p>;
  if (detail === null) {
    return (
      <section>
        <button type="button" onClick={onBack}>
          ← Results
        </button>
        <p role="alert">This recipe did not load.</p>
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
  return (
    <article aria-labelledby="recipe-h">
      <button type="button" onClick={onBack}>
        ← Results
      </button>
      <h2 id="recipe-h" tabIndex={-1}>{detail.title}</h2>
      {meta.length > 0 && <p>{meta.join(" | ")}</p>}
      <h3>Ingredients</h3>
      <ul class="lines">
        {detail.lines.map((ln, i) => {
          const status = lineStatus(ln, have, stapleSet);
          return (
            <li key={i}>
              <span class={`tag tag-${status}`}>[{STATUS_LABEL[status]}]</span> {ln.t}
            </li>
          );
        })}
      </ul>
      <h3>Steps</h3>
      <ol>
        {detail.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
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
    </article>
  );
}
