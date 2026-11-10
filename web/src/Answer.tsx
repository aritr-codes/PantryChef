import { useEffect, useMemo, useRef } from "preact/hooks";
import type { Engine } from "./engine";
import { recipeSlots } from "./slots";
import { ticket, ticketText } from "./ticket";
import { UndoBar, type Undo } from "./UndoBar";
import type { Answer as AnswerData, RecipeResult } from "./types";

export type Tab = "make_now" | "one_away" | "two_away";
const TABS: { key: Tab; lead: string; rest: string }[] = [
  { key: "make_now", lead: "Ready", rest: "now" },
  { key: "one_away", lead: "One item", rest: "away" },
  { key: "two_away", lead: "Two items", rest: "away" },
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
  onTry: (id: string, name: string) => void;
  clearUndo: () => void;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function headline(a: AnswerData, n: number): string {
  const { make_now: now, one_away: one, two_away: two } = a.groups;
  if (n === 0) return "Start with what you have.";
  if (now.count > 0) return `You can make ${plural(now.count, "recipe", "recipes")} now.`;
  if (one.count > 0) {
    return `Nothing is ready yet. ${plural(one.count, "recipe is", "recipes are")} one item away.`;
  }
  if (two.count > 0) {
    return `Nothing is close yet. ${plural(two.count, "recipe is", "recipes are")} two items away.`;
  }
  return "No recipe matches yet.";
}

function Row(p: {
  r: RecipeResult;
  engine: Engine;
  pantry: ReadonlySet<string>;
  staples: ReadonlySet<string>;
  onOpen: (id: string) => void;
}) {
  const { slots, check } = recipeSlots(p.engine.line(p.r.recipe_id) ?? [], (id) => p.engine.name(id), p.pantry, p.staples);
  return (
    <li class="card">
      <button type="button" class="card-link" onClick={() => p.onOpen(p.r.recipe_id)}>
        {p.r.title}
      </button>
      <p class="meta">
        {p.r.have} of {p.r.total} in your kitchen
        {check > 0 ? `, ${plural(check, "line", "lines")} to check` : ""}
      </p>
      <ul class="slots" aria-label="Ingredients">
        {slots.map((s) => (
          <li key={s.kind + s.name} class={`slot slot-${s.kind}`}>
            {s.kind === "need" && <span aria-hidden="true">+ </span>}
            <span class="sr">{s.kind === "have" ? "Have: " : s.kind === "need" ? "Missing: " : "Assumed: "}</span>
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
  const t = ticket(answer);
  const none = answer.groups.make_now.count + answer.groups.one_away.count + answer.groups.two_away.count === 0;

  // After "Show more", move focus to the first new row, so the button's removal does not drop focus.
  const list = useRef<HTMLUListElement>(null);
  const shownBefore = useRef(group.items.length);
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current && group.items.length > shownBefore.current) {
      list.current?.querySelectorAll<HTMLElement>(".card-link")[shownBefore.current]?.focus();
      asked.current = false;
    }
    shownBefore.current = group.items.length;
  }, [group.items.length]);

  // After "Try it with", the ticket can change or go. If focus was lost, put it on the tab.
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

  const emptyNote: Record<Tab, string> = {
    make_now: "Nothing is ready yet. Look at what is one item away, or add more items.",
    one_away: "Nothing is one item away yet. Add a few more items.",
    two_away: "Nothing is two items away yet. Add a few more items.",
  };

  return (
    <section class="answer" aria-labelledby="answer-h">
      <div class="wrapslip">
        <div class="slip">
          <div class="row">
            <h2 class="label" id="answer-h" tabIndex={-1} data-focus-heading>What you can cook</h2>
            {n > 0 && <span class="label dim">{n} {n === 1 ? "item" : "items"} + staples</span>}
          </div>
          <p class="big" role="status" aria-live="polite">{headline(answer, n)}</p>

          {n === 0 ? (
            <div class="empty">
              <p>Your recipes appear here as you add items. Each recipe shows its ingredients as a strip.</p>
              <ul class="key">
                <li><span class="slot slot-have">Solid</span> you have it</li>
                <li><span class="slot slot-need"><span aria-hidden="true">+ </span>Dashed</span> you need it</li>
                <li><span class="slot slot-assumed">Outline</span> assumed, like salt</li>
              </ul>
            </div>
          ) : (
            <>
              <div class="tabs" role="tablist" aria-label="How far each recipe is from your kitchen">
                {TABS.map((tb, i) => (
                  <button
                    key={tb.key}
                    type="button"
                    role="tab"
                    id={`tab-${tb.key}`}
                    data-k={tb.key}
                    aria-selected={p.tab === tb.key}
                    aria-controls="panel"
                    tabIndex={p.tab === tb.key ? 0 : -1}
                    onClick={() => p.setTab(tb.key)}
                    onKeyDown={(e) => onTabKey(e, i)}
                  >
                    <span class="num">{answer.groups[tb.key].count}</span>
                    <span class="tab-label">
                      <b>{tb.lead}</b> {tb.rest}
                    </span>
                  </button>
                ))}
              </div>
              <div id="panel" role="tabpanel" aria-labelledby={`tab-${p.tab}`}>
                <UndoBar where="ticket" undo={p.undo} onDone={p.clearUndo} />
                {t && (
                  <div class="buy" role="group" aria-labelledby="buy-h">
                    <h3 class="label" id="buy-h">Buy one thing</h3>
                    <p class="thing">{t.name}</p>
                    <p class="mono">{ticketText(t)}</p>
                    <button
                      type="button"
                      class="btn"
                      onClick={() => {
                        tried.current = true;
                        p.onTry(t.id, t.name);
                      }}
                    >
                      Try it with {t.name}
                    </button>
                  </div>
                )}
                {group.count > 0 && (
                  <>
                    <ul class="cards" ref={list}>
                      {group.items.map((r) => (
                        <Row key={r.recipe_id} r={r} engine={p.engine} pantry={pantry} staples={staples} onOpen={p.onOpen} />
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
                {group.count === 0 && !none && <p class="mono empty-note">{emptyNote[p.tab]}</p>}
                {none && (
                  <div class="empty">
                    <h3 class="label">No recipes match yet</h3>
                    {answer.blockers.length > 0 ? (
                      <ul class="blockers">
                        {answer.blockers.slice(0, 3).map((b) => (
                          <li key={b.ingredient_id ?? b.name}>
                            Add {b.name} to get {plural(b.recipes, "recipe", "recipes")}.{" "}
                            {b.ingredient_id && (
                              <button
                                type="button"
                                class="linkbtn"
                                onClick={() => {
                                  tried.current = true;
                                  p.onTry(b.ingredient_id as string, b.name);
                                }}
                              >
                                Try it with {b.name}
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
            </>
          )}
          <hr class="hr solid" />
          <p class="src">
            Recipes are written by Wikibooks cooks and shown with their licence. Results come from your list and the
            recipes, not from an AI model.
          </p>
        </div>
      </div>
    </section>
  );
}
