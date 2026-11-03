import { useState } from "preact/hooks";
import type { Engine } from "./engine";
import type { Answer } from "./types";

interface Props {
  engine: Engine;
  ids: string[];
  unknown: string[];
  staples: string[];
  answer: Answer;
  setIds: (ids: string[]) => void;
  setUnknown: (names: string[]) => void;
  setStaples: (ids: string[]) => void;
  onSee: () => void;
}

export function PantryScreen(p: Props) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const suggestions = text.trim() ? p.engine.suggest(text) : [];
  const count = p.ids.length;
  const now = p.answer.groups.make_now.count;
  const one = p.answer.groups.one_away.count;

  const addId = (id: string) => {
    if (!p.ids.includes(id)) p.setIds([...p.ids, id]);
    setText("");
    setActive(-1);
  };
  const addText = (raw: string) => {
    const name = raw.trim();
    if (!name) return;
    const { ids } = p.engine.resolve([name]);
    if (ids[0]) addId(ids[0]);
    else {
      if (!p.unknown.includes(name)) p.setUnknown([...p.unknown, name]);
      setText("");
      setActive(-1);
    }
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
      const take = pick ?? (exact ? undefined : suggestions[0]);
      if (take) addId(take.id);
      else addText(text);
    } else if (e.key === "Escape") {
      setText("");
      setActive(-1);
    }
  };
  const toggleStaple = (id: string) =>
    p.setStaples(p.staples.includes(id) ? p.staples.filter((s) => s !== id) : [...p.staples, id]);
  const stapleIds = p.engine.defaultStaples;
  const quick = p.engine.popular(24).filter((s) => !p.ids.includes(s.id));

  return (
    <section aria-labelledby="pantry-h">
      <h2 id="pantry-h">What do you have?</h2>
      <label for="ingredient">Type an ingredient</label>
      <div class="row">
        <input
          id="ingredient"
          type="text"
          role="combobox"
          autocomplete="off"
          aria-expanded={suggestions.length > 0}
          aria-controls="suggestions"
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `sug-${active}` : undefined}
          value={text}
          onInput={(e) => {
            setText((e.target as HTMLInputElement).value);
            setActive(-1);
          }}
          onKeyDown={onKeyDown}
        />
        <button type="button" onClick={() => addText(text)}>
          Add
        </button>
      </div>
      {suggestions.length > 0 && (
        <ul id="suggestions" role="listbox" aria-label="Suggestions">
          {suggestions.map((s, i) => (
            <li
              key={s.id}
              id={`sug-${i}`}
              role="option"
              aria-selected={i === active}
              onClick={() => addId(s.id)}
            >
              {s.name}
            </li>
          ))}
        </ul>
      )}

      <h3>Your pantry ({count})</h3>
      <ul class="chips" aria-label="Your pantry">
        {p.ids.map((id) => (
          <li key={id}>
            {p.engine.name(id)}
            <button
              type="button"
              aria-label={`Remove ${p.engine.name(id)}`}
              onClick={() => p.setIds(p.ids.filter((x) => x !== id))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      {p.unknown.map((name) => (
        <p key={name} class="unknown">
          Not recognised: “{name}”. It is not used for matching.{" "}
          {p.engine.suggest(name, 3).map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                p.setUnknown(p.unknown.filter((n) => n !== name));
                addId(s.id);
              }}
            >
              Use {s.name}
            </button>
          ))}
          <button type="button" onClick={() => p.setUnknown(p.unknown.filter((n) => n !== name))}>
            Remove “{name}”
          </button>
        </p>
      ))}

      <h3>Quick add</h3>
      <ul class="chips" aria-label="Quick add">
        {quick.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => addId(s.id)}>
              {s.name}
            </button>
          </li>
        ))}
      </ul>

      <details>
        <summary>Staples assumed ({p.staples.length})</summary>
        <p>PantryChef assumes you always have these. Switch off any you lack.</p>
        {stapleIds.map((id) => (
          <label key={id} class="check">
            <input
              type="checkbox"
              checked={p.staples.includes(id)}
              onChange={() => toggleStaple(id)}
            />{" "}
            {p.engine.name(id)}
          </label>
        ))}
      </details>

      <p role="status" aria-live="polite" class="hint">
        {count === 0
          ? "Add an item to start."
          : count < 3
            ? "Add more items for better matches."
            : ""}
      </p>
      <button type="button" class="primary" disabled={count === 0} onClick={p.onSee}>
        {count === 0 ? "See recipes (add an item first)" : `See recipes: ${now} now, ${one} one away`}
      </button>
    </section>
  );
}
