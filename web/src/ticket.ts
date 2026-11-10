// The "Buy one thing" ticket: the engine's top unlock, plus recipe titles to make it concrete.
// Titles come only from the one-away items the engine already returned. The engine is not changed.

import type { Answer } from "./types";

const TITLES = 3;

export interface Ticket {
  id: string;
  name: string;
  recipes: number; // the engine's count
  titles: string[]; // up to three, from the returned items
  more: number; // recipes - titles.length
}

export function ticket(answer: Answer): Ticket | null {
  const top = answer.unlocks[0];
  if (!top) return null;
  const titles = answer.groups.one_away.items
    .filter((r) => r.missing.length === 1 && r.missing[0]?.options.includes(top.ingredient_id))
    .slice(0, TITLES)
    .map((r) => r.title);
  return {
    id: top.ingredient_id,
    name: top.name,
    recipes: top.recipes,
    titles,
    more: Math.max(top.recipes - titles.length, 0),
  };
}

export function ticketText(t: Ticket): string {
  const noun = t.recipes === 1 ? "recipe" : "recipes";
  if (t.titles.length === 0) return `Opens ${t.recipes} ${noun}.`;
  const last = t.titles[t.titles.length - 1] as string;
  const head = t.titles.slice(0, -1);
  if (t.more > 0) return `Opens ${t.recipes} ${noun}: ${t.titles.join(", ")} and ${t.more} more.`;
  const list = head.length ? `${head.join(", ")} and ${last}` : last;
  return `Opens ${t.recipes} ${noun}: ${list}.`;
}
