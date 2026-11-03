import type { Engine } from "./engine";
import type { Answer, RecipeResult } from "./types";

interface Props {
  engine: Engine;
  answer: Answer;
  itemCount: number;
  onBack: () => void;
  onMore: () => void;
  onOpen: (recipeId: string) => void;
}

function missingText(engine: Engine, r: RecipeResult): string {
  return r.missing
    .map((m) =>
      m.options.length ? m.options.map((o) => engine.name(o)).join(" or ") : `Check this line: ${m.text}`,
    )
    .join("; ");
}

function Card({ r, engine, onOpen }: { r: RecipeResult; engine: Engine; onOpen: (id: string) => void }) {
  const missing = missingText(engine, r);
  return (
    <li class="card">
      <button type="button" class="card-link" onClick={() => onOpen(r.recipe_id)}>
        {r.title}
      </button>
      <p>
        You have {r.have} of {r.total} (staples assumed)
        {missing ? `. Missing: ${missing}` : ""}
      </p>
    </li>
  );
}

function Section(props: {
  id: string;
  title: string;
  group: Answer["groups"]["make_now"];
  engine: Engine;
  onOpen: (id: string) => void;
  onMore: () => void;
  collapsed?: boolean;
}) {
  const { group } = props;
  if (group.count === 0) return null;
  const body = (
    <>
      <ul class="cards">
        {group.items.map((r) => (
          <Card key={r.recipe_id} r={r} engine={props.engine} onOpen={props.onOpen} />
        ))}
      </ul>
      {group.items.length < group.count && (
        <button type="button" onClick={props.onMore}>
          Show more ({group.count - group.items.length} left)
        </button>
      )}
    </>
  );
  return (
    <section aria-labelledby={props.id}>
      {props.collapsed ? (
        <details>
          <summary id={props.id}>
            {props.title} ({group.count})
          </summary>
          {body}
        </details>
      ) : (
        <>
          <h3 id={props.id}>
            {props.title} ({group.count})
          </h3>
          {body}
        </>
      )}
    </section>
  );
}

export function ResultsScreen({ engine, answer, itemCount, onBack, onMore, onOpen }: Props) {
  const { make_now, one_away, two_away } = answer.groups;
  const none = make_now.count + one_away.count + two_away.count === 0;
  const showTwo = make_now.count + one_away.count < 5;
  return (
    <section aria-labelledby="results-h">
      <button type="button" onClick={onBack}>
        ← Pantry
      </button>
      <h2 id="results-h">Results for {itemCount} {itemCount === 1 ? "item" : "items"}</h2>
      {itemCount < 3 && <p>Add more items for better matches.</p>}
      {answer.unknown_pantry.length > 0 && (
        <p>Not used for matching: {answer.unknown_pantry.join(", ")}</p>
      )}
      <Section id="h-now" title="Make now" group={make_now} engine={engine} onOpen={onOpen} onMore={onMore} />
      <Section id="h-one" title="One item away" group={one_away} engine={engine} onOpen={onOpen} onMore={onMore} />
      {answer.unlocks.length > 0 && (
        <section aria-labelledby="h-unlock">
          <h3 id="h-unlock">Top unlocks</h3>
          <ul>
            {answer.unlocks.slice(0, 5).map((u) => (
              <li key={u.ingredient_id}>
                Add {u.name} to move {u.recipes} {u.recipes === 1 ? "recipe" : "recipes"} to make now
              </li>
            ))}
          </ul>
        </section>
      )}
      {showTwo && (
        <Section id="h-two" title="Two items away" group={two_away} engine={engine} onOpen={onOpen} onMore={onMore} collapsed />
      )}
      {none && (
        <section aria-labelledby="h-none">
          <h3 id="h-none">No recipes match yet</h3>
          {answer.blockers.length > 0 ? (
            <ul>
              {answer.blockers.slice(0, 3).map((b) => (
                <li key={b.ingredient_id}>
                  Add {b.name} to get {b.recipes} {b.recipes === 1 ? "recipe" : "recipes"}
                </li>
              ))}
            </ul>
          ) : (
            <p>Try adding more or different items.</p>
          )}
        </section>
      )}
    </section>
  );
}
