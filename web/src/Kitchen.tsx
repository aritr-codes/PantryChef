import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Icon } from "./Icon";
import { UndoBar, type Undo } from "./UndoBar";
import type { Engine } from "./engine";
import type { Example } from "./examples";
import { cap, mergeRestore, resolveList } from "./list";
import { useRecent } from "./recent";

interface Props {
  engine: Engine;
  ids: string[];
  unknown: string[];
  staples: string[];
  examples: Example[];
  open: boolean; // phone only: the full kitchen is shown
  undo: Undo | null;
  setOpen: (open: boolean) => void;
  setIds: (ids: string[] | ((cur: string[]) => string[])) => void;
  setUnknown: (names: string[] | ((cur: string[]) => string[])) => void;
  setStaples: (ids: string[]) => void;
  onExample: (example: Example) => void;
  say: (message: string) => void;
  notify: (undo: Undo) => void;
  clearUndo: () => void;
}

const QUICK = 10;
const STAMPS = 5; // more stamps than this are summarised, so a big paste stays fast
const SUMMARY = 6;
const LIST_BREAK = /[,;\n\r]|\sand\s/i;

export function Kitchen(p: Props) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const [paste, setPaste] = useState(false);
  const [pasted, setPasted] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const chips = useRef<HTMLUListElement>(null);
  const quickList = useRef<HTMLUListElement>(null);
  const pending = useRef<(() => void) | null>(null);
  // Run a focus move after the next render, so it lands on the new DOM.
  useEffect(() => {
    pending.current?.();
    pending.current = null;
  });
  const fresh = useRecent(p.ids);

  const stamps = p.unknown.slice(0, STAMPS);
  // Suggestions for each stamp, worked out once per list and not on every keystroke.
  const stampHints = useMemo(() => stamps.map((n) => p.engine.suggest(n, 1)), [p.engine, stamps.join("\n")]);
  const suggestions = text.trim() ? p.engine.suggest(text, 5) : [];
  const count = p.ids.length;
  const empty = count === 0;
  const stapleIds = p.engine.defaultStaples;
  const popular = useMemo(() => p.engine.popular(40), [p.engine]);
  const quick = popular.filter((s) => !p.ids.includes(s.id)).slice(0, QUICK);
  const names = p.ids.map((id) => p.engine.name(id));
  const summary = names.slice(0, SUMMARY).join(", ") + (count > SUMMARY ? ` and ${count - SUMMARY} more` : "");

  const reset = () => {
    setText("");
    setActive(-1);
  };
  const addId = (id: string) => {
    if (!p.ids.includes(id)) {
      p.setIds([...p.ids, id]);
      p.say(`${cap(p.engine.name(id))} added.`);
    }
    reset();
  };
  /** Read a list, add what is known, keep the rest as "not on the list". */
  const addList = (raw: string) => {
    const { ids, unknown } = resolveList(raw, (n) => p.engine.resolve(n));
    const added = ids.filter((id) => !p.ids.includes(id));
    if (added.length) p.setIds([...p.ids, ...added]);
    const newWords = unknown.filter((u) => !p.unknown.some((x) => x.toLowerCase() === u.toLowerCase()));
    if (newWords.length) p.setUnknown([...p.unknown, ...newWords]);
    const said = [
      added.length ? `${cap(added.map((id) => p.engine.name(id)).join(", "))} added.` : "",
      newWords.length ? `Not on the list: ${newWords.join(", ")}.` : "",
    ].filter(Boolean);
    if (said.length) p.say(said.join(" "));
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(Math.min(active + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(Math.max(active - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = suggestions[active];
      const exact = suggestions.find((s) => s.name.toLowerCase() === text.trim().toLowerCase());
      const take = pick ?? (exact || LIST_BREAK.test(text) ? undefined : suggestions[0]);
      if (take) addId(take.id);
      else {
        addList(text);
        reset();
      }
    } else if (e.key === "Escape") {
      reset();
    }
  };
  const onInput = (e: Event) => {
    const value = (e.target as HTMLInputElement).value;
    // A comma or semicolon ends an item, so "egg," adds egg.
    if (/[,;]/.test(value)) {
      addList(value);
      reset();
      return;
    }
    setText(value);
    setActive(-1);
  };
  const onPaste = (e: ClipboardEvent) => {
    const pastedText = e.clipboardData?.getData("text") ?? "";
    if (LIST_BREAK.test(pastedText.trim())) {
      e.preventDefault();
      addList(pastedText);
    }
  };

  const remove = (id: string, index: number) => {
    p.setIds(p.ids.filter((x) => x !== id));
    p.say(`${cap(p.engine.name(id))} removed.`);
    pending.current = () => {
      const left = chips.current?.querySelectorAll<HTMLElement>("button");
      (left?.[index] ?? left?.[left.length - 1] ?? input.current)?.focus();
    };
  };
  const quickAdd = (id: string, index: number) => {
    addId(id);
    pending.current = () => {
      const left = quickList.current?.querySelectorAll<HTMLElement>("button");
      (left?.[index] ?? left?.[left.length - 1] ?? input.current)?.focus();
    };
  };
  const clearAll = () => {
    const before = { ids: p.ids, unknown: p.unknown };
    p.setIds([]);
    p.setUnknown([]);
    p.notify({
      where: "kitchen",
      msg: "Kitchen cleared.",
      run: () => {
        p.setIds((cur) => mergeRestore(before.ids, cur));
        p.setUnknown((cur) => mergeRestore(before.unknown, cur));
        p.say("Kitchen restored.");
      },
    });
    pending.current = () => input.current?.focus();
  };
  // The stamp goes away when it is used, so focus returns to the field.
  const dismiss = (name: string) => {
    p.setUnknown(p.unknown.filter((n) => n !== name));
    pending.current = () => input.current?.focus();
  };
  const toggleStaple = (id: string) =>
    p.setStaples(p.staples.includes(id) ? p.staples.filter((s) => s !== id) : [...p.staples, id]);
  const allStaples = () => p.setStaples(p.staples.length > 0 ? [] : stapleIds);
  const stapleNames = stapleIds.map((id) => p.engine.name(id)).join(", ");

  return (
    <section class={`kitchen${p.open ? " open" : ""}`} aria-label="Your kitchen">
      <div class="wrap">
        <div class="slip">
          <div class="full">
            <div class="head">
              <p class="kicker">Your kitchen</p>
              <p class="kicker">
                {count} {count === 1 ? "item" : "items"}
              </p>
            </div>
            <h2 id="kitchen-h">What you have</h2>
            {empty ? (
              <div class="empty">
                <p>Your kitchen is empty. Add what you have, or start with an example.</p>
                <ol class="how" role="list">
                  <li>Add what you have.</li>
                  <li>See what you can cook now.</li>
                  <li>See what 1 more item would add.</li>
                </ol>
                {p.examples.length > 0 && (
                  <>
                    <p class="kicker how-label">Start with an example</p>
                    <ul class="examples" role="list">
                      {p.examples.map((ex) => (
                        <li key={ex.name}>
                          <button type="button" class="ex" onClick={() => p.onExample(ex)}>
                            <b>{ex.name}</b>
                            <span>
                              {ex.ids
                                .slice(0, 5)
                                .map((id) => p.engine.name(id))
                                .join(", ")}
                              {ex.ids.length > 5 ? " and more" : ""}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    <p class="small">You can change an example after you pick it.</p>
                  </>
                )}
              </div>
            ) : (
              <ul class="pantry" role="list" ref={chips} aria-label="Items in your kitchen">
                {p.ids.map((id, i) => (
                  <li key={id}>
                    <button
                      type="button"
                      class={`have${fresh.has(id) ? " pop" : ""}`}
                      aria-label={`Remove ${p.engine.name(id)}`}
                      onClick={() => remove(id, i)}
                    >
                      <Icon name={p.engine.name(id)} />
                      {p.engine.name(id)}
                      <span class="x" aria-hidden="true">×</span>
                    </button>
                    {p.staples.includes(id) && <span class="quiet"> (a staple, always assumed)</span>}
                  </li>
                ))}
              </ul>
            )}

            <div class="field">
              <label for="ingredient">Add what you have</label>
              <div class="ctl">
                <input
                  id="ingredient"
                  ref={input}
                  type="text"
                  role="combobox"
                  autocomplete="off"
                  spellcheck={false}
                  enterkeyhint="done"
                  placeholder="eggs, rice, a lemon"
                  aria-expanded={suggestions.length > 0}
                  aria-controls="suggestions"
                  aria-autocomplete="list"
                  aria-describedby="ingredient-hint"
                  aria-activedescendant={active >= 0 ? `sug-${active}` : undefined}
                  value={text}
                  onInput={onInput}
                  onKeyDown={onKeyDown}
                  onPaste={onPaste}
                />
                {suggestions.length > 0 && (
                  <ul id="suggestions" class="sugg" role="listbox" aria-label="Suggestions">
                    {suggestions.map((s, i) => (
                      <li
                        key={s.id}
                        id={`sug-${i}`}
                        role="option"
                        aria-selected={i === active}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => addId(s.id)}
                      >
                        <Icon name={s.name} />
                        {s.name}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p class="small" id="ingredient-hint">
                Type 1 item and press Enter. Or paste a list. Use commas or new lines.
              </p>
            </div>
            <UndoBar where="kitchen" undo={p.undo} onDone={p.clearUndo} />

            {stamps.map((name, n) => (
              <div key={name} class="stamp" role="group" aria-label={`Not on the list: ${name}`}>
                <b>Not on the list</b>
                <p>We do not know “{name}” yet.</p>
                <div class="row">
                  {(stampHints[n] ?? []).map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => {
                        dismiss(name);
                        addId(s.id);
                      }}
                    >
                      Use {s.name} instead
                    </button>
                  ))}
                  <button type="button" aria-label={`Dismiss “${name}”`} onClick={() => dismiss(name)}>
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
            {p.unknown.length > STAMPS && (
              <div class="stamp" role="group" aria-label="More words not on the list">
                <p>and {p.unknown.length - STAMPS} more not on the list. We do not use them.</p>
                <div class="row">
                  <button
                    type="button"
                    onClick={() => {
                      p.setUnknown([]);
                      pending.current = () => input.current?.focus();
                    }}
                  >
                    Dismiss all
                  </button>
                </div>
              </div>
            )}

            {quick.length > 0 && (
              <div class="quick">
                <h3 class="kicker">Tap to add</h3>
                <ul class="chips" role="list" ref={quickList}>
                  {quick.map((s, i) => (
                    <li key={s.id}>
                      <button type="button" class="add" onClick={() => quickAdd(s.id, i)}>
                        <Icon name={s.name} />
                        <span aria-hidden="true">+ </span>
                        <span class="sr">Add </span>
                        {s.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div class="staples sw">
              <h3 class="kicker">Staples</h3>
              <label>
                <input type="checkbox" checked={p.staples.length > 0} onChange={allStaples} />
                <span>
                  <b>Count these as mine</b>
                  {stapleNames}. You do not need to add them.
                </span>
              </label>
              <details>
                <summary>Choose staples ({p.staples.length} on)</summary>
                {stapleIds.map((id) => (
                  <label key={id}>
                    <input type="checkbox" checked={p.staples.includes(id)} onChange={() => toggleStaple(id)} />
                    <span>{p.engine.name(id)}</span>
                  </label>
                ))}
              </details>
            </div>

            <div class="acts">
              <button type="button" class="link" aria-expanded={paste} aria-controls="paste-box" onClick={() => setPaste(!paste)}>
                Paste a list
              </button>
              {(count > 0 || p.unknown.length > 0) && (
                <button type="button" class="link" onClick={clearAll}>
                  Clear all
                </button>
              )}
            </div>
            {paste && (
              <div class="paste" id="paste-box">
                <label class="sr" for="paste">Paste ingredients</label>
                <textarea
                  id="paste"
                  rows={5}
                  placeholder={"eggs, spinach, 2 onions\nrice and lemon"}
                  value={pasted}
                  onInput={(e) => setPasted((e.target as HTMLTextAreaElement).value)}
                />
                <button
                  type="button"
                  class="btn"
                  onClick={() => {
                    addList(pasted);
                    setPasted("");
                    setPaste(false);
                    pending.current = () => input.current?.focus();
                  }}
                >
                  Add these
                </button>
              </div>
            )}
            {!empty && (
              <button
                type="button"
                class="btn primary done"
                onClick={() => {
                  p.setOpen(false);
                  pending.current = () => document.getElementById("edit-kitchen")?.focus();
                }}
              >
                Done
              </button>
            )}
          </div>

          <div class="sum">
            <div class="head">
              <p class="kicker">Your kitchen</p>
              <p class="kicker">
                {count} {count === 1 ? "item" : "items"}
              </p>
            </div>
            <p class="sum-text">{empty ? "Nothing yet." : summary}</p>
            <button
              type="button"
              class="btn"
              id="edit-kitchen"
              onClick={() => {
                p.setOpen(true);
                pending.current = () => input.current?.focus();
              }}
            >
              {empty ? "Add what you have" : "Edit kitchen"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
