import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { PantryScreen } from "./PantryScreen";
import { RecipeScreen } from "./RecipeScreen";
import { ResultsScreen } from "./ResultsScreen";
import { type Engine, ready } from "./engine";

type Screen = { name: "pantry" } | { name: "results" } | { name: "recipe"; id: string };

const PAGE = 10;
const PACK_URL = (import.meta.env.VITE_PACK_URL as string | undefined) ?? "./pack/";

export function App() {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: "pantry" });
  const [ids, setIds] = useState<string[]>([]);
  const [unknown, setUnknown] = useState<string[]>([]);
  const [staples, setStaples] = useState<string[]>([]);
  const [shown, setShown] = useState(PAGE);
  const first = useRef(true);
  const screenName = screen.name === "recipe" ? `recipe:${screen.id}` : screen.name;

  // Move focus to the new screen's heading, so keyboard and screen-reader users know it changed.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo(0, 0);
    document.querySelector<HTMLElement>("main h2")?.focus();
  }, [screenName]);

  useEffect(() => {
    ready(PACK_URL)
      .then((e) => {
        setEngine(e);
        setStaples(e.defaultStaples);
      })
      .catch(() => setError("The recipe data did not load. Check your connection and reload."));
  }, []);

  const answer = useMemo(
    () =>
      engine?.answer({ pantry: ids, staples, diet: null, limit: shown, unknown_names: unknown }),
    [engine, ids, staples, shown, unknown],
  );

  if (error) return <main><p role="alert">{error}</p></main>;
  if (!engine || !answer) return <main><p role="status">Loading recipes…</p></main>;

  const goPantry = () => setScreen({ name: "pantry" });
  return (
    <main>
      <header>
        <h1>PantryChef</h1>
      </header>
      {screen.name === "pantry" && (
        <PantryScreen
          engine={engine}
          ids={ids}
          unknown={unknown}
          staples={staples}
          answer={answer}
          setIds={setIds}
          setUnknown={setUnknown}
          setStaples={setStaples}
          onSee={() => {
            setShown(PAGE);
            setScreen({ name: "results" });
          }}
        />
      )}
      {screen.name === "results" && (
        <ResultsScreen
          engine={engine}
          answer={answer}
          itemCount={ids.length}
          onBack={goPantry}
          onMore={() => setShown(shown + PAGE)}
          onOpen={(id) => setScreen({ name: "recipe", id })}
        />
      )}
      {screen.name === "recipe" && (
        <RecipeScreen
          engine={engine}
          recipeId={screen.id}
          pantry={ids}
          staples={staples}
          onBack={() => setScreen({ name: "results" })}
        />
      )}
      <footer>
        <p>Nothing you type leaves this device. Recipes come from the Wikibooks Cookbook.</p>
      </footer>
    </main>
  );
}
