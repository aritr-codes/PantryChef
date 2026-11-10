// The strip of slots on a recipe row: one slot per ingredient line.
// HAVE is solid, NEED is dashed with a plus, ASSUMED is a quiet outline. Optional lines and
// lines the pack could not read are left out of the strip. Unread lines are counted instead.

import { lineStatus } from "./status";
import type { CoreLine, IngredientId } from "./types";

export type SlotKind = "have" | "need" | "assumed";
export interface Slot {
  kind: SlotKind;
  name: string;
}

export function recipeSlots(
  lines: readonly CoreLine[],
  name: (id: IngredientId) => string,
  pantry: ReadonlySet<IngredientId>,
  staples: ReadonlySet<IngredientId>,
): { slots: Slot[]; check: number } {
  const slots: Slot[] = [];
  let check = 0;
  const push = (kind: SlotKind, text: string) => {
    if (!slots.some((s) => s.kind === kind && s.name === text)) slots.push({ kind, name: text });
  };
  for (const ln of lines) {
    const status = lineStatus(ln, pantry, staples);
    if (status === "check") check += 1;
    else if (status === "have") push("have", name(ln.o.find((o) => pantry.has(o)) as string));
    else if (status === "assumed") push("assumed", name(ln.o.find((o) => staples.has(o)) as string));
    else if (status === "missing") push("need", ln.o.map(name).join(" or "));
  }
  return { slots, check };
}
