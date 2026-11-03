// Browser engine. It must give the same results as pantrychef/engine.py (ADR 0004).
// Rules: docs/ARCHITECTURE_PROPOSAL.md sections 5 and 6, "Rules fixed while building M1".
// The app calls only this module. It never reads data files itself.

import { tokens } from "./normalize";
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

  constructor(readonly core: Core) {
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

  /** Map typed names to ids by exact canonical key. Mirrors `resolve_names` in Python. */
  resolve(names: string[]): { ids: IngredientId[]; unknown: string[] } {
    const ids: IngredientId[] = [];
    const unknown: string[] = [];
    for (const name of names) {
      const hit = this.core.keys[tokens(name).join(" ")];
      if (hit === undefined) unknown.push(name);
      else if (!ids.includes(hit)) ids.push(hit);
    }
    return { ids, unknown };
  }

  /** Autocomplete over names and synonyms. Prefix matches rank first, then shorter names. */
  suggest(text: string, limit = 8): Suggestion[] {
    const raw = text.normalize("NFKD").replace(/\p{Mn}/gu, "").toLowerCase().trim();
    if (raw === "") return [];
    const found = (q: string): Suggestion[] => {
      const hits = new Map<IngredientId, { rank: number; len: number }>();
      for (const [key, id] of Object.entries(this.core.keys)) {
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

  answer(request: AnswerRequest): Answer {
    if (request.diet !== null) throw new Error("diet flags arrive in M5");
    const staples = new Set(request.staples);
    const unknownIds = [...new Set(request.pantry.filter((i) => !this.idf.has(i)))].sort();
    const pantry = new Set(request.pantry.filter((i) => this.idf.has(i) && !staples.has(i)));

    const grouped: RecipeResult[][] = [[], [], []];
    const oneAwayLines: CoreLine[] = [];
    const scan: { needed: CoreLine[]; total: number; have: number }[] = [];

    for (const recipe of this.core.recipes) {
      const needed = recipe.lines.filter((ln) => !ln.opt && !ln.o.some((o) => staples.has(o)));
      const total = needed.length;
      if (total === 0) continue;
      const satisfied = needed.map((ln) => ln.o.some((o) => pantry.has(o)));
      const have = satisfied.filter(Boolean).length;
      scan.push({ needed, total, have });
      if (have === 0 || total - have > 2) continue;
      let num = 0;
      let den = 0;
      needed.forEach((ln, k) => {
        let w = 0;
        for (const o of ln.o) w = Math.max(w, this.idf.get(o) ?? 0);
        den += w;
        if (satisfied[k]) num += w;
      });
      const score = den > 0 ? num / Math.sqrt(den) : 0;
      const missingLines = needed.filter((_, k) => !satisfied[k]);
      if (missingLines.length === 1 && missingLines[0]) oneAwayLines.push(missingLines[0]);
      grouped[missingLines.length]?.push({
        recipe_id: recipe.id,
        title: recipe.title,
        have,
        total,
        score,
        missing: missingLines.map((ln) => ({ options: [...ln.o], text: ln.t, swap: null })),
        unread: missingLines.filter((ln) => !ln.r).length,
        diet_state: null,
        reasons: [],
      });
    }

    const limit = Math.max(request.limit, 0);
    const groups = {} as Answer["groups"];
    GROUP_KEYS.forEach((key, n) => {
      const items = [...(grouped[n] ?? [])].sort(
        (a, b) =>
          b.score - a.score ||
          a.total - b.total ||
          (a.recipe_id < b.recipe_id ? -1 : a.recipe_id > b.recipe_id ? 1 : 0),
      );
      const g: Group = { count: items.length, items: items.slice(0, limit) };
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
      for (const { needed, total, have } of scan) {
        const perItem = new Map<string, number>();
        for (const ln of needed) {
          if (ln.o.some((o) => pantry.has(o))) continue;
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
  const stream = res.body?.pipeThrough(new DecompressionStream("gzip"));
  if (!stream) throw new Error(`${url}: no body`);
  return JSON.parse(await new Response(stream).text()) as T;
}

/** Load `<name>.v1.json.gz`, or the plain `.json` copy (used by the test fixture pack). */
async function loadPackFile<T>(base: string, name: string, doFetch: typeof fetch): Promise<T> {
  try {
    return await readJson<T>(`${base}${name}.v1.json.gz`, true, doFetch);
  } catch {
    return await readJson<T>(`${base}${name}.v1.json`, false, doFetch);
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
