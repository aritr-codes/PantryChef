// The "Buy one thing" ticket: the engine's top unlock, plus recipe titles to make it concrete.
// Titles come only from the one-away items the engine already returned. The engine is not changed.

import type { Answer, AnswerRequest } from "./types";

const TITLES = 3;

export interface Ticket {
  id: string;
  name: string;
  recipes: number; // how many more recipes are ready now with the item (the real gain)
  titles: string[]; // up to three, from the returned items
  more: number; // recipes - titles.length
}

/**
 * How many recipes are ready now after the item is added. This asks the engine again with the item
 * in the kitchen, so it counts every recipe that opens. The engine's unlock count does not: it
 * misses a recipe whose only needed line is the item, and a recipe that needs the item twice.
 */
export function readyAfter(
  engine: { answer(request: AnswerRequest): Answer },
  pantry: string[],
  staples: string[],
  id: string,
): number {
  const request = { pantry: [...pantry, id], staples, diet: null, limit: 0, unknown_names: [] };
  return engine.answer(request).groups.make_now.count;
}

export function ticket(answer: Answer, after: number): Ticket | null {
  const top = answer.unlocks[0];
  if (!top) return null;
  const gain = Math.max(after - answer.groups.make_now.count, 0);
  const titles = answer.groups.one_away.items
    .filter((r) => r.missing.length === 1 && r.missing[0]?.options.includes(top.ingredient_id))
    .slice(0, TITLES)
    .map((r) => r.title);
  return {
    id: top.ingredient_id,
    name: top.name,
    recipes: gain,
    titles,
    more: Math.max(gain - titles.length, 0),
  };
}

/** "With x, you can cook 3 more: A, B and C." The count is the full gain, and the titles may be fewer. */
export function ticketText(t: Ticket): string {
  const head = `With ${t.name}, you can cook ${t.recipes} more`;
  if (t.titles.length === 0) return `${head}.`;
  if (t.more > 0) return `${head}: ${t.titles.join(", ")} and ${t.more} more.`;
  const last = t.titles[t.titles.length - 1] as string;
  const rest = t.titles.slice(0, -1);
  return `${head}: ${rest.length ? `${rest.join(", ")} and ${last}` : last}.`;
}