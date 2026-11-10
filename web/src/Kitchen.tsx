import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { Engine } from "./engine";
import { mergeRestore, resolveList } from "./list";
import { UndoBar, type Undo } from "./UndoBar";

interface Props {
  engine: Engine;
  ids: string[];
  unknown: string[];
  staples: string[];
  saved: boolean;
  open: boolean; // phone only: the full kitchen is shown
  undo: Undo | null;
  setOpen: (open: boolean) => void;
  setIds: (ids: string[] | ((cur: string[]) => string[])) => void;
  setUnknown: (names: string[] | ((cur: string[]) => string[])) => void;
  setStaples: (ids: string[]) => void;
  say: (message: string) => void;
  notify: (undo: Undo) => void;
  clearUndo: () => void;
}

const QUICK = 10;
const STAMPS = 5; // more stamps than this are summarised, so a big paste stays fast
const LIST_BREAK = /[,;\n\r]|\sand\s/i;

export function Kitchen(p: Props) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const [paste, setPaste] = useState(false);
  const [pasted, setPasted] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const words = useRef<HTMLUListElement>(null);
  const quickList = useRef<HTMLUListElement>(null);
  const pending = useRef<(() => void) | null>(null);
  // Run a focus move after the next render, so it lands on the new DOM.
  useEffect(() => {
    pending.current?.();
    pending.current = null;
  });

  const stamps = p.unknown.slice(0, STAMPS);
  // Suggestions for each stamp, worked out once per list and not on every keystroke.
  const stampHints = useMemo(() => stamps.map((n) => p.engine.suggest(n, 3)), [p.engine, stamps.join("\n")]);
  const suggestions = text.trim() ? p.engine.suggest(text) : [];
  const count = p.ids.length;
  const empty = count === 0;
  const stapleIds = p.engine.defaultStaples;
  const popular = useMemo(() => p.engine.popular(40), [p.engine]);
  const quick = popular.filter((s) => !p.ids.includes(s.id)).slice(0, QUICK);
  const first = p.ids.slice(0, 3).map((id) => p.engine.name(id));
  const summary = first.join(", ") + (count > 3 ? ` +${count - 3} more` : "");

  const reset = () => {
    setText("");
    setActive(-1);
  };
  const addId = (id: string) => {
    if (!p.ids.includes(id)) {
      p.setIds([...p.ids, id]);
      p.say(`${p.engine.name(id)} added.`);
    }
    reset();
  };
  /** Read a list, add what is known, keep the rest as "not on the list". */
  const addList = (raw: string) => {
    const { ids, unknown } = resolveList(raw, (n) => p.engine.resolve(n));
    const added = ids.filter((id) => !p.ids.includes(id));
    if (added.length) p.setIds([...p.ids, ...added]);
    const fresh = unknown.filter((u) => !p.unknown.some((x) => x.toLowerCase() === u.toLowerCase()));
    if (fresh.length) p.setUnknown([...p.unknown, ...fresh]);
    const said = [
      added.length ? `${added.map((id) => p.engine.name(id)).join(", ")} added.` : "",
      fresh.length ? `Not on the list: ${fresh.join(", ")}.` : "",
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
    p.say(`${p.engine.name(id)} removed.`);
    pending.current = () => {
      const left = words.current?.querySelectorAll<HTMLElement>("button");
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

  return (
    <section class="kitchen" data-open={String(p.open)} aria-labelledby="kitchen-h">
      <div class="wrapslip">
        <div class="slip">
          <div class="row">
            <h2 class="label" id="kitchen-h">Your kitchen</h2>
            <span class="label dim">
              {count} {count === 1 ? "item" : "items"}
            </span>
          </div>
          <p class="note">
            {p.saved
              ? "Saved on this device. Never sent anywhere."
              : "Not saved: this browser blocks storage. Never sent anywhere."}
          </p>
          <UndoBar where="kitchen" undo={p.undo} onDone={p.clearUndo} />

          <div class="summary">
            <p class="mono">{summary}</p>
            <button
              type="button"
              class="btn"
              id="edit-kitchen"
              onClick={() => {
                p.setOpen(true);
                pending.current = () => input.current?.focus();
              }}
            >
              Edit kitchen
            </button>
          </div>

          <div class="full">
            {empty ? (
              <p class="mono lead-in">Nothing in your kitchen yet. Type or paste what you have below.</p>
            ) : (
              <ul class="words" ref={words} aria-label="Your kitchen. Tap an item to remove it.">
                {p.ids.map((id, i) => (
                  <li key={id}>
                    <button type="button" class="word" aria-label={`Remove ${p.engine.name(id)}`} onClick={() => remove(id, i)}>
                      {p.engine.name(id)}
                    </button>
                    {p.staples.includes(id) && <span class="quiet"> (staple, always assumed)</span>}
                  </li>
                ))}
              </ul>
            )}

            <label class="label add-label" for="ingredient">Add ingredients</label>
            <div class="prompt">
              <b aria-hidden="true">&gt;</b>
              <input
                id="ingredient"
                ref={input}
                type="text"
                role="combobox"
                autocomplete="off"
                spellcheck={false}
                enterkeyhint="done"
                placeholder="eggs, spinach, rice and lemon"
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
            </div>
            <p class="note" id="ingredient-hint">Separate items with commas, new lines or “and”. Press Enter to add.</p>
            {suggestions.length > 0 && (
              <ul id="suggestions" class="sug" role="listbox" aria-label="Suggestions">
                {suggestions.map((s, i) => (
                  <li
                    key={s.id}
                    id={`sug-${i}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => addId(s.id)}
                  >
                    {s.name}
                  </li>
                ))}
              </ul>
            )}

            {stamps.map((name, n) => (
              <div key={name} class="stamp" role="group" aria-label={`Not on the list: ${name}`}>
                <p>
                  Not on the list: “{name}”. It is not used for matching.
                </p>
                {(stampHints[n] ?? []).map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    class="btn"
                    onClick={() => {
                      dismiss(name);
                      addId(s.id);
                    }}
                  >
                    Use {s.name}
                  </button>
                ))}
                <button type="button" class="btn" aria-label={`Dismiss “${name}”`} onClick={() => dismiss(name)}>
                  Dismiss
                </button>
              </div>
            ))}
            {p.unknown.length > STAMPS && (
              <div class="stamp" role="group" aria-label="More words not on the list">
                <p>
                  and {p.unknown.length - STAMPS} more not on the list. They are not used for matching.
                </p>
                <button
                  type="button"
                  class="btn"
                  onClick={() => {
                    p.setUnknown([]);
                    pending.current = () => input.current?.focus();
                  }}
                >
                  Dismiss all
                </button>
              </div>
            )}

            {quick.length > 0 && (
              <>
                <h3 class="label quick-label">Quick add</h3>
                <ul class="tap" ref={quickList}>
                  {quick.map((s, i) => (
                    <li key={s.id}>
                      <button type="button" onClick={() => quickAdd(s.id, i)}>
                        <span aria-hidden="true">+ </span>
                        <span class="sr">Add </span>
                        {s.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}

            <hr class="hr" />
            <details class="staples">
              <summary>
                Staples assumed ({p.staples.length})
              </summary>
              <p class="note">PantryChef assumes you always have these. Switch off any you lack.</p>
              {stapleIds.map((id) => (
                <label key={id} class="check">
                  <input type="checkbox" checked={p.staples.includes(id)} onChange={() => toggleStaple(id)} />{" "}
                  {p.engine.name(id)}
                </label>
              ))}
            </details>

            <div class="row tools">
              <button type="button" class="linkbtn" aria-expanded={paste} aria-controls="paste-box" onClick={() => setPaste(!paste)}>
                Paste a list
              </button>
              {(count > 0 || p.unknown.length > 0) && (
                <button type="button" class="linkbtn" onClick={clearAll}>
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
                class="btn done"
                onClick={() => {
                  p.setOpen(false);
                  pending.current = () => document.getElementById("edit-kitchen")?.focus();
                }}
              >
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
