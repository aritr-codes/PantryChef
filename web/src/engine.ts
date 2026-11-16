// Browser engine. It must give the same results as pantrychef/engine.py (ADR 0004).
// Rules: docs/ARCHITECTURE_PROPOSAL.md sections 5 and 6, "Rules fixed while building M1".
// The app calls only this module. It never reads data files itself.

import { resolveName } from "./names";
import { tokens } from "./normalize";
import { makeWords, type Words } from "./units";
import type {
  Answer,
  AnswerRequest,
  Blocker,
  Core,
  CoreLine,
  CoreRecipe,
  Group,
  IngredientId,
  RecipeDetail,
  RecipeResult,
  Unlock,
} from "./types";

const UNLOCK_LIMIT = 10;
const BLOCKER_LIMIT = 5;
const GROUP_KEYS = ["make_now", "one_away", "two_away"] as const;

interface TextEntry {
  steps: string[];
  servings: string | null;
  time: string | null;
  category: string | null;
  url: string;
  revision_url: string;
  revision_id: number;
  licence: string;
  retrieved_on: string;
  changes: string | null;
}
interface TextPack {
  format: number;
  recipes: Record<string, TextEntry>;
}

/** The lines of one recipe that count for a given set of staples, with the weight of each line. */
interface Prepared {
  recipe: CoreRecipe;
  lines: CoreLine[];
  w: number[];
}

export interface Suggestion {
  id: IngredientId;
  name: string;
}

function byCountThenId(a: [string, number], b: [string, number]): number {
  return b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
}

export class Engine {
  private readonly idf = new Map<IngredientId, number>();
  private readonly names = new Map<IngredientId, string>();
  private readonly byId = new Map<string, CoreRecipe>();
  readonly words: Words;
  // The needed lines depend on the staples only, and the staples seldom change. Keep the last result.
  private preparedKey: string | null = null;
  private preparedFor: Prepared[] = [];
  private keyList: [string, IngredientId][] | null = null;

  constructor(readonly core: Core) {
    this.words = makeWords(core.words);
    for (const i of core.ingredients) {
      this.idf.set(i.id, i.idf);
      this.names.set(i.id, i.name);
    }
    for (const r of core.recipes) this.byId.set(r.id, r);
  }

  get defaultStaples(): IngredientId[] {
    return this.core.ingredients.filter((i) => i.staple).map((i) => i.id);
  }

  name(id: IngredientId): string {
    return this.names.get(id) ?? id;
  }

  /** The most common non-staple ingredients, for the quick-add grid (lowest idf first). */
  popular(n: number): Suggestion[] {
    return this.core.ingredients
      .filter((i) => !i.staple && i.idf > 0)
      .sort((a, b) => a.idf - b.idf || (a.id < b.id ? -1 : 1))
      .slice(0, n)
      .map((i) => ({ id: i.id, name: i.name }));
  }

  /** Map typed names to ids (see names.ts). Mirrors `resolve_names` in Python. */
  resolve(names: string[]): { ids: IngredientId[]; unknown: string[] } {
    const ids: IngredientId[] = [];
    const unknown: string[] = [];
    for (const name of names) {
      const match = resolveName(name, this.core.keys, this.words);
      if (match.step === "none") unknown.push(name);
      for (const id of match.ids) if (!ids.includes(id)) ids.push(id);
    }
    return { ids, unknown };
  }

  /** Autocomplete over names and synonyms. Prefix matches rank first, then shorter names. */
  suggest(text: string, limit = 8): Suggestion[] {
    const raw = text.normalize("NFKD").replace(/\p{Mn}/gu, "").toLowerCase().trim();
    if (raw === "") return [];
    const found = (q: string): Suggestion[] => {
      const hits = new Map<IngredientId, { rank: number; len: number }>();
      this.keyList ??= Object.entries(this.core.keys);
      for (const [key, id] of this.keyList) {
        const rank = key.startsWith(q) ? 0 : key.includes(" " + q) ? 1 : -1;
        if (rank < 0) continue;
        const prev = hits.get(id);
        if (!prev || rank < prev.rank || (rank === prev.rank && key.length < prev.len)) {
          hits.set(id, { rank, len: key.length });
        }
      }
      return [...hits.entries()]
        .sort((a, b) => a[1].rank - b[1].rank || a[1].len - b[1].len || (a[0] < b[0] ? -1 : 1))
        .slice(0, limit)
        .map(([id]) => ({ id, name: this.name(id) }));
    };
    const first = found(raw);
    return first.length ? first : found(tokens(text).join(" "));
  }

  /** Per recipe: the lines that count (not optional, not a staple) and the weight of each. */
  private prepared(staples: ReadonlySet<string>): Prepared[] {
    const key = [...staples].sort().join("\u0000");
    if (key === this.preparedKey) return this.preparedFor;
    const out: Prepared[] = [];
    for (const recipe of this.core.recipes) {
      const lines = recipe.lines.filter((ln) => !ln.opt && !ln.o.some((o) => staples.has(o)));
      if (lines.length === 0) continue;
      const w = lines.map((ln) => {
        let best = 0;
        for (const o of ln.o) best = Math.max(best, this.idf.get(o) ?? 0);
        return best;
      });
      out.push({ recipe, lines, w });
    }
    this.preparedKey = key;
    this.preparedFor = out;
    return out;
  }

  /** How many recipes are ready now. It gives the same count as `answer`, and it stops early on each recipe. */
  readyCount(pantryIds: string[], stapleIds: string[]): number {
    const staples = new Set(stapleIds);
    const pantry = new Set(pantryIds.filter((i) => this.idf.has(i) && !staples.has(i)));
    let ready = 0;
    recipes: for (const { lines } of this.prepared(staples)) {
      for (const ln of lines) {
        if (!ln.o.some((o) => pantry.has(o))) continue recipes;
      }
      ready++;
    }
    return ready;
  }

  answer(request: AnswerRequest): Answer {
    if (request.diet !== null) throw new Error("diet flags arrive in M5");
    const staples = new Set(request.staples);
    const unknownIds = [...new Set(request.pantry.filter((i) => !this.idf.has(i)))].sort();
    const pantry = new Set(request.pantry.filter((i) => this.idf.has(i) && !staples.has(i)));
    const prepared = this.prepared(staples);
    const has = (ln: CoreLine): boolean => {
      for (const o of ln.o) if (pantry.has(o)) return true;
      return false;
    };

    // Keep a light entry per candidate. Only the entries that are shown become full results.
    interface Candidate {
      recipe: CoreRecipe;
      have: number;
      total: number;
      score: number;
      missing: CoreLine[];
    }
    const grouped: Candidate[][] = [[], [], []];
    const oneAwayLines: CoreLine[] = [];

    for (const { recipe, lines, w } of prepared) {
      // Count the lines the pantry covers. Stop when a third line is missing: the recipe is out.
      let have = 0;
      let miss = 0;
      for (const ln of lines) {
        if (has(ln)) have++;
        else if (++miss > 2) break;
      }
      if (miss > 2 || have === 0) continue;
      let num = 0;
      let den = 0;
      const missing: CoreLine[] = [];
      for (let k = 0; k < lines.length; k++) {
        const ln = lines[k] as CoreLine;
        den += w[k] as number;
        if (has(ln)) num += w[k] as number;
        else missing.push(ln);
      }
      const score = den > 0 ? num / Math.sqrt(den) : 0;
      if (missing.length === 1 && missing[0]) oneAwayLines.push(missing[0]);
      grouped[missing.length]?.push({ recipe, have, total: lines.length, score, missing });
    }

    const limit = Math.max(request.limit, 0);
    const groups = {} as Answer["groups"];
    GROUP_KEYS.forEach((key, n) => {
      const items = [...(grouped[n] ?? [])].sort(
        (a, b) =>
          b.score - a.score ||
          a.total - b.total ||
          (a.recipe.id < b.recipe.id ? -1 : a.recipe.id > b.recipe.id ? 1 : 0),
      );
      const shown: RecipeResult[] = items.slice(0, limit).map((c) => ({
        recipe_id: c.recipe.id,
        title: c.recipe.title,
        have: c.have,
        total: c.total,
        score: c.score,
        missing: c.missing.map((ln) => ({ options: [...ln.o], text: ln.t, swap: null })),
        unread: c.missing.filter((ln) => !ln.r).length,
        diet_state: null,
        reasons: [],
      }));
      const g: Group = { count: items.length, items: shown };
      groups[key] = g;
    });

    const counts = new Map<string, number>();
    for (const ln of oneAwayLines) for (const o of ln.o) counts.set(o, (counts.get(o) ?? 0) + 1);
    const unlocks: Unlock[] = [...counts.entries()]
      .sort(byCountThenId)
      .slice(0, UNLOCK_LIMIT)
      .map(([id, n]) => ({ ingredient_id: id, name: this.name(id), recipes: n }));

    let blockers: Blocker[] = [];
    const allEmpty = GROUP_KEYS.every((k) => groups[k].count === 0);
    if (allEmpty && pantry.size > 0) {
      const gains = new Map<string, number>();
      for (const { lines: needed } of prepared) {
        const total = needed.length;
        const have = needed.filter(has).length;
        const perItem = new Map<string, number>();
        for (const ln of needed) {
          if (has(ln)) continue;
          for (const o of ln.o) {
            if (this.idf.has(o) && !staples.has(o)) perItem.set(o, (perItem.get(o) ?? 0) + 1);
          }
        }
        for (const [item, gain] of perItem) {
          if (have + gain >= 1 && total - (have + gain) <= 2) {
            gains.set(item, (gains.get(item) ?? 0) + 1);
          }
        }
      }
      blockers = [...gains.entries()]
        .sort(byCountThenId)
        .slice(0, BLOCKER_LIMIT)
        .map(([id, n]) => ({ kind: "add_item", ingredient_id: id, name: this.name(id), recipes: n }));
    }

    return {
      groups,
      unlocks,
      blockers,
      unknown_pantry: [...request.unknown_names, ...unknownIds],
      pack: {
        version: this.core.info.version,
        commit: this.core.info.commit,
        corpus_fingerprint: this.core.info.corpus_fingerprint,
      },
    };
  }

  line(recipeId: string): CoreLine[] | undefined {
    return this.byId.get(recipeId)?.lines;
  }
}

// ---- loading -------------------------------------------------------------------------------

async function readJson<T>(url: string, gz: boolean, doFetch: typeof fetch): Promise<T> {
  const res = await doFetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  if (!gz) return (await res.json()) as T;
  // Some servers send .gz files with "Content-Encoding: gzip", and the browser then decodes them.
  // Check the gzip magic bytes so both cases work.
  const bytes = new Uint8Array(await res.arrayBuffer());
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return JSON.parse(new TextDecoder().decode(bytes)) as T;
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text()) as T;
}

/** Load `<name>.v2.json.gz`, or the plain `.json` copy (used by the test fixture pack). */
async function loadPackFile<T>(base: string, name: string, doFetch: typeof fetch): Promise<T> {
  try {
    return await readJson<T>(`${base}${name}.v2.json.gz`, true, doFetch);
  } catch {
    return await readJson<T>(`${base}${name}.v2.json`, false, doFetch);
  }
}

let current: { engine: Engine; base: string; doFetch: typeof fetch } | null = null;
let textPack: Promise<TextPack> | null = null;

export async function ready(base = "./pack/", doFetch: typeof fetch = fetch): Promise<Engine> {
  const core = await loadPackFile<Core>(base, "core", doFetch);
  current = { engine: new Engine(core), base, doFetch };
  textPack = null;
  return current.engine;
}

function engine(): Engine {
  if (!current) throw new Error("engine is not ready");
  return current.engine;
}

export const suggest = (text: string, limit?: number): Suggestion[] =>
  engine().suggest(text, limit);
export const answer = (req: AnswerRequest): Answer => engine().answer(req);
export const resolve = (names: string[]) => engine().resolve(names);
export const popular = (n: number): Suggestion[] => engine().popular(n);
export const defaultStaples = (): IngredientId[] => engine().defaultStaples;
export const ingredientName = (id: IngredientId): string => engine().name(id);

/** Full recipe detail. Loads the text pack on first use. */
export async function recipe(recipeId: string): Promise<RecipeDetail | null> {
  const cur = current;
  if (!cur) throw new Error("engine is not ready");
  textPack ??= loadPackFile<TextPack>(cur.base, "text", cur.doFetch);
  const entry = (await textPack).recipes[recipeId];
  const r = cur.engine.core.recipes.find((x) => x.id === recipeId);
  if (!entry || !r) return null;
  return {
    recipe_id: recipeId,
    title: r.title,
    lines: r.lines,
    steps: entry.steps,
    servings: entry.servings,
    time: entry.time,
    category: entry.category,
    source: {
      url: entry.url,
      revision_url: entry.revision_url,
      revision_id: entry.revision_id,
      licence: entry.licence,
      retrieved_on: entry.retrieved_on,
      changes: entry.changes,
    },
  };
}

/** Swap hints arrive in M5. */
export function swaps(): null {
  return null;
}
