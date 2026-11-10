import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { AnswerPanel, type Tab, defaultTab } from "./Answer";
import { Kitchen } from "./Kitchen";
import { RecipeScreen } from "./RecipeScreen";
import type { Undo } from "./UndoBar";
import { type Engine, ready } from "./engine";
import { type Saved, load, save, storageWorks } from "./store";

type Screen = { name: "board" } | { name: "recipe"; id: string };

const PAGE = 10;
const UNDO_MS = 12_000;
const PACK_URL = (import.meta.env.VITE_PACK_URL as string | undefined) ?? "./pack/";

function Frame(p: { children: ComponentChildren }) {
  return (
    <main>
      <header class="top">
        <h1 class="mark">PantryChef</h1>
        <p class="tagline">What can you cook with what you have?</p>
      </header>
      {p.children}
    </main>
  );
}

export function App() {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: "board" });
  const [ids, setIds] = useState<string[]>([]);
  const [unknown, setUnknown] = useState<string[]>([]);
  const [staples, setStaples] = useState<string[]>([]);
  const [shown, setShown] = useState(PAGE);
  const [picked, setPicked] = useState<Tab | null>(null);
  // Phone only: the full kitchen is shown. It starts open, and stays open while the kitchen is empty.
  const [open, setOpen] = useState(true);
  const [saved, setSaved] = useState(true);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [announce, setAnnounce] = useState("");
  const first = useRef(true);
  const latest = useRef<Saved | null>(null); // what to save if the page closes before the effect runs
  const screenName = screen.name === "recipe" ? `recipe:${screen.id}` : screen.name;

  // Move focus to the answer heading when the person comes back from a recipe. The recipe screen
  // focuses its own heading once the recipe has loaded.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo(0, 0);
    if (screen.name === "board") document.querySelector<HTMLElement>("[data-focus-heading]")?.focus();
  }, [screenName]);

  useEffect(() => {
    ready(PACK_URL)
      .then((e) => {
        const known = new Set(e.core.ingredients.map((i) => i.id));
        const s = load(known);
        setEngine(e);
        setStaples(s ? e.defaultStaples.filter((id) => !s.staplesOff.includes(id)) : e.defaultStaples);
        if (s) setIds(s.ids);
        if (s?.ids.length) setOpen(false);
        setSaved(storageWorks());
      })
      .catch(() => setError("The recipe data did not load. Check your connection and reload."));
  }, []);

  // Save ids and the staple switches. Typed text that was not recognised is never saved.
  useEffect(() => {
    if (!engine) return;
    setSaved(save({ ids, staplesOff: engine.defaultStaples.filter((id) => !staples.includes(id)) }));
  }, [engine, ids, staples]);

  // Also save when the page is hidden or closed, so a quick reload cannot lose the last change.
  useEffect(() => {
    const flush = () => {
      if (latest.current) save(latest.current);
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  useEffect(() => {
    if (ids.length === 0) setOpen(true);
  }, [ids.length]);

  useEffect(() => {
    if (!undo) return;
    const timer = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(timer);
  }, [undo]);

  const say = (message: string) => {
    setAnnounce("");
    setTimeout(() => setAnnounce(message), 50);
  };

  const answer = useMemo(
    () =>
      engine?.answer({ pantry: ids, staples, diet: null, limit: shown, unknown_names: unknown }),
    [engine, ids, staples, shown, unknown],
  );

  latest.current = engine
    ? { ids, staplesOff: engine.defaultStaples.filter((id) => !staples.includes(id)) }
    : null;

  if (error) {
    return (
      <Frame>
        <p role="alert">{error}</p>
        <button type="button" class="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </Frame>
    );
  }
  if (!engine || !answer) {
    return (
      <Frame>
        <p role="status">Loading recipes…</p>
      </Frame>
    );
  }

  const tab = picked ?? defaultTab(answer);
  const tryItem = (id: string, name: string) => {
    if (ids.includes(id)) return;
    setIds([...ids, id]);
    setUndo({
      where: "ticket",
      msg: `Added ${name}.`,
      run: () => {
        setIds((cur) => cur.filter((x) => x !== id));
      },
    });
  };

  return (
    <Frame>
      {screen.name === "board" ? (
        <div class="grid">
          <Kitchen
            engine={engine}
            ids={ids}
            unknown={unknown}
            staples={staples}
            saved={saved}
            open={open}
            undo={undo}
            setOpen={setOpen}
            setIds={setIds}
            setUnknown={setUnknown}
            setStaples={setStaples}
            say={say}
            notify={setUndo}
            clearUndo={() => setUndo(null)}
          />
          <AnswerPanel
            engine={engine}
            answer={answer}
            ids={ids}
            staples={staples}
            tab={tab}
            undo={undo}
            setTab={setPicked}
            onMore={() => setShown(shown + PAGE)}
            onOpen={(id) => setScreen({ name: "recipe", id })}
            onTry={tryItem}
            clearUndo={() => setUndo(null)}
          />
        </div>
      ) : (
        <RecipeScreen
          engine={engine}
          recipeId={screen.id}
          pantry={ids}
          staples={staples}
          onBack={() => setScreen({ name: "board" })}
        />
      )}
      <div class="sr" role="status" aria-live="polite">{announce}</div>
      <footer class="page">
        <p>
          Nothing you type leaves this device. {saved ? "Your kitchen is saved in this browser only, and you can clear it at any time." : "Your kitchen is not saved, because this browser blocks storage."} Recipes come from the Wikibooks Cookbook, with their licence.
        </p>
      </footer>
    </Frame>
  );
}
