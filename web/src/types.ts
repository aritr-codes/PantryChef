// Hand-written contract types. They mirror pantrychef/engine.py (ARCHITECTURE_PROPOSAL section 5).
// The golden parity tests catch drift between the two.

export type IngredientId = string;

export interface CoreLine {
  t: string; // the line as the page wrote it
  o: IngredientId[]; // acceptable ids; empty when the line is unread
  opt: boolean;
  r: boolean; // read
}

export interface CoreRecipe {
  id: string;
  title: string;
  page: string;
  rev: number;
  lines: CoreLine[];
}

export interface CoreIngredient {
  id: IngredientId;
  name: string;
  staple: boolean;
  idf: number;
}

export interface Core {
  format: number;
  info: { version: string; commit: string; corpus_fingerprint: string; recipes: number };
  ingredients: CoreIngredient[];
  keys: Record<string, IngredientId>;
  recipes: CoreRecipe[];
}

export interface AnswerRequest {
  pantry: IngredientId[];
  staples: IngredientId[];
  diet: null; // diet flags arrive in M5
  limit: number;
  unknown_names: string[];
}

export interface Missing {
  options: IngredientId[];
  text: string;
  swap: null;
}

export interface RecipeResult {
  recipe_id: string;
  title: string;
  have: number;
  total: number;
  score: number;
  missing: Missing[];
  unread: number;
  diet_state: null;
  reasons: string[];
}

export interface Group {
  count: number;
  items: RecipeResult[];
}

export interface Unlock {
  ingredient_id: IngredientId;
  name: string;
  recipes: number;
}

export interface Blocker {
  kind: "add_item";
  ingredient_id: IngredientId | null;
  name: string;
  recipes: number;
}

export interface PackInfo {
  version: string;
  commit: string;
  corpus_fingerprint: string;
}

export interface Answer {
  groups: { make_now: Group; one_away: Group; two_away: Group };
  unlocks: Unlock[];
  blockers: Blocker[];
  unknown_pantry: string[];
  pack: PackInfo;
}

export interface Attribution {
  url: string;
  revision_url: string;
  revision_id: number;
  licence: string;
  retrieved_on: string;
  changes: string | null;
}

export interface RecipeDetail {
  recipe_id: string;
  title: string;
  lines: CoreLine[];
  steps: string[];
  servings: string | null;
  time: string | null;
  category: string | null;
  source: Attribution;
}
