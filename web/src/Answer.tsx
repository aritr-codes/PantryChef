import { useEffect, useMemo, useRef } from "preact/hooks";
import { Icon } from "./Icon";
import { UndoBar, type Undo } from "./UndoBar";
import type { Engine } from "./engine";
import { useRecent } from "./recent";
import { recipeSlots } from "./slots";
import { readyAfter, ticket, ticketText } from "./ticket";
import type { Answer as AnswerData, RecipeResult } from "./types";

export type Tab = "make_now" | "one_away" | "two_away";
const TABS: { key: Tab; label: string }[] = [
  { key: "make_now", label: "Ready now" },
  { key: "one_away", label: "Need 1 thing" },
  { key: "two_away", label: "Need 2 things" },
];

/** The tab to show when the person has not picked one: the nearest group that has recipes. */
export function defaultTab(a: AnswerData): Tab {
  if (a.groups.make_now.count > 0) return "make_now";
  if (a.groups.one_away.count > 0) return "one_away";
  if (a.groups.two_away.count > 0) return "two_away";
  return "make_now";
}

interface Props {
  engine: Engine;
  answer: AnswerData;
  ids: string[];
  staples: string[];
  tab: Tab;
  undo: Undo | null;
  setTab: (tab: Tab) => void;
  onMore: () => void;
  onOpen: (recipeId: string) => void;
  onTry: (id: string, name: string, gain: number) => void;
  clearUndo: () => void;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function lead(a: AnswerData, tab: Tab, n: number) {
  const c = a.groups[tab].count;
  if (n === 0) return "Add a few things. Recipes show here.";
  if (tab === "make_now") {
    if (c === 0) return "Nothing is ready now. Look at the recipes that need 1 thing.";
    return (
      <>
        <mark>{plural(c, "recipe is", "recipes are")}</mark> ready now.
      </>
    );
  }
  return (
    <>
      <mark>{plural(c, "recipe needs", "recipes need")}</mark> {tab === "one_away" ? "1 thing" : "2 things"}.
    </>
  );
}

function Row(p: {
  r: RecipeResult;
  engine: Engine;
  pantry: ReadonlySet<string>;
  staples: ReadonlySet<string>;
  slide: boolean;
  onOpen: (id: string) => void;
}) {
  const { slots, check } = recipeSlots(p.engine.line(p.r.recipe_id) ?? [], (id) => p.engine.name(id), p.pantry, p.staples);
  return (
    <li class={`rec${p.slide ? " slide" : ""}`}>
      <div class="name">
        <button type="button" class="rec-link" data-recipe={p.r.recipe_id} onClick={() => p.onOpen(p.r.recipe_id)}>
          {p.r.title}
        </button>
        <span class="meta">
          {p.r.have} of {p.r.total}
          <span class="sr"> ingredients you have</span>
          {check > 0 ? ` · ${plural(check, "line", "lines")} to check` : ""}
        </span>
      </div>
      <ul class="slots" role="list" aria-label="Ingredients">
        {slots.map((s) => (
          <li key={s.kind + s.name} class={`s ${s.kind === "have" ? "h" : s.kind === "need" ? "n" : "a"}`}>
            <span class="sr">{s.kind === "have" ? "You have " : s.kind === "need" ? "You need " : "Assumed: "}</span>
            {s.kind === "have" && <span aria-hidden="true">✓ </span>}
            {s.kind === "need" && <span aria-hidden="true">+ </span>}
            {s.name}
          </li>
        ))}
      </ul>
    </li>
  );
}

export function AnswerPanel(p: Props) {
  const { answer } = p;
  const n = p.ids.length;
  const pantry = useMemo(() => new Set(p.ids), [p.ids]);
  const staples = useMemo(() => new Set(p.staples), [p.staples]);
  const group = answer.groups[p.tab];
  // One more scan with the top item added, so the ticket shows the real count that opens.
  const topId = answer.unlocks[0]?.ingredient_id;
  const after = useMemo(
    () => (topId && n > 0 ? readyAfter(p.engine, p.ids, p.staples, topId) : 0),
    [p.engine, p.ids, p.staples, topId, n],
  );
  const t = ticket(answer, after);
  const now = answer.groups.make_now.count;
  const none = answer.groups.make_now.count + answer.groups.one_away.count + answer.groups.two_away.count === 0;
  const showTicket = n > 0 && t && p.tab !== "two_away";

  // Short entry animations. They are CSS only, and CSS plays them only when motion is allowed.
  const bumped = useRecent(
    TABS.map((tb) => `${tb.key}:${answer.groups[tb.key].count}`),
  );
  const slid = useRecent(group.items.map((r) => r.recipe_id), 700, p.tab);
  const torn = useRecent(t ? [t.id] : []);

  // After "Show more", move focus to the first new row, so the button's removal does not drop focus.
  const list = useRef<HTMLUListElement>(null);
  const shownBefore = useRef(group.items.length);
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current && group.items.length > shownBefore.current) {
      list.current?.querySelectorAll<HTMLElement>(".rec-link")[shownBefore.current]?.focus();
      asked.current = false;
    }
    shownBefore.current = group.items.length;
  }, [group.items.length]);

  // After "Add <item>", the ticket can change or go. If focus was lost, put it on the tab.
  const tried = useRef(false);
  useEffect(() => {
    if (!tried.current) return;
    tried.current = false;
    if (document.activeElement === document.body) document.getElementById(`tab-${p.tab}`)?.focus();
  });

  const onTabKey = (e: KeyboardEvent, i: number) => {
    const to =
      e.key === "ArrowRight" ? (i + 1) % 3 : e.key === "ArrowLeft" ? (i + 2) % 3 : e.key === "Home" ? 0 : e.key === "End" ? 2 : -1;
    if (to < 0) return;
    e.preventDefault();
    const next = TABS[to]!.key;
    p.setTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  };

  return (
    <section id="answer" class="answer" tabIndex={-1} aria-label="What you can cook">
      <div class="wrap">
        <div class="slip">
          <div class="head">
            <p class="kicker">Tonight</p>
            <p class="kicker">
              From {n} {n === 1 ? "item" : "items"}
              {p.staples.length > 0 ? " + staples" : ""}
            </p>
          </div>
          <div class="counts" role="tablist" aria-label="How close you are">
            {TABS.map((tb, i) => (
              <button
                key={tb.key}
                type="button"
                role="tab"
                class="count"
                id={`tab-${tb.key}`}
                aria-selected={p.tab === tb.key}
                aria-controls="panel"
                tabIndex={p.tab === tb.key ? 0 : -1}
                onClick={() => p.setTab(tb.key)}
                onKeyDown={(e) => onTabKey(e, i)}
              >
                <span class={`n${bumped.has(`${tb.key}:${answer.groups[tb.key].count}`) ? " bump" : ""}`}>
                  {answer.groups[tb.key].count}
                </span>
                <span class="t">{tb.label}</span>
              </button>
            ))}
          </div>
          <h2 class="lead" id="answer-h" tabIndex={-1} data-focus-heading aria-live="polite">
            {lead(answer, p.tab, n)}
          </h2>

          {showTicket && (
            <div class={`ticket${torn.has(t.id) ? " tear" : ""}`} role="group" aria-labelledby="buy-h">
              <h3 class="kicker" id="buy-h">Buy 1 thing</h3>
              <p class="what">
                <Icon name={t.name} />
                {t.name}
              </p>
              <p class="gain">
                <span class="big" aria-hidden="true">
                  <span class="from">{now}</span>
                  <span class="arrow">→</span>
                  <span class="to">{now + t.recipes}</span>
                </span>
                <span class="lbl" aria-hidden="true">ready now, with {t.name}</span>
                <span class="sr">
                  From {now} to {now + t.recipes} ready now, with {t.name}.
                </span>
              </p>
              <p class="why">{ticketText(t)}</p>
              <button
                type="button"
                class="btn"
                onClick={() => {
                  tried.current = true;
                  p.onTry(t.id, t.name, t.recipes);
                }}
              >
                Add {t.name}
              </button>
              <p class="note">This adds {t.name} to your kitchen. You can undo it.</p>
            </div>
          )}
          <UndoBar where="ticket" undo={p.undo} onDone={p.clearUndo} />

          <div id="panel" role="tabpanel" tabIndex={0} aria-labelledby={`tab-${p.tab}`}>
            {group.count > 0 && (
              <>
                <ul class="list" role="list" ref={list}>
                  {group.items.map((r) => (
                    <Row
                      key={r.recipe_id}
                      r={r}
                      engine={p.engine}
                      pantry={pantry}
                      staples={staples}
                      slide={slid.has(r.recipe_id)}
                      onOpen={p.onOpen}
                    />
                  ))}
                </ul>
                {group.items.length < group.count && (
                  <button
                    type="button"
                    class="btn more"
                    onClick={() => {
                      asked.current = true;
                      p.onMore();
                    }}
                  >
                    Show more ({group.count - group.items.length} left)
                  </button>
                )}
              </>
            )}
            {group.count === 0 && n > 0 && !none && (
              <p class="none">No recipes here yet. Add an item, or open another tab.</p>
            )}
            {none && n > 0 && (
              <div class="none">
                <h3 class="kicker">No recipes match yet</h3>
                {answer.blockers.length > 0 ? (
                  <ul class="blockers" role="list">
                    {answer.blockers.slice(0, 3).map((b) => (
                      <li key={b.ingredient_id ?? b.name}>
                        Add {b.name} to get {plural(b.recipes, "recipe", "recipes")}.{" "}
                        {b.ingredient_id && (
                          <button
                            type="button"
                            class="link"
                            onClick={() => {
                              tried.current = true;
                              p.onTry(b.ingredient_id as string, b.name, 0);
                            }}
                          >
                            Add {b.name}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Try adding more or different items.</p>
                )}
              </div>
            )}
          </div>
          <p class="foot">
            Recipes come from Wikibooks cooks and show their licence. The results come from your list and the recipes.
            An AI model does not write them.
          </p>
        </div>
      </div>
    </section>
  );
}
