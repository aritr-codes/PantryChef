// How one recipe line looks to this pantry. The label is text, so colour is never the only cue.

import type { CoreLine, IngredientId } from "./types";

export type LineStatus = "have" | "missing" | "assumed" | "optional" | "check";

export const STATUS_LABEL: Record<LineStatus, string> = {
  have: "You have it",
  missing: "You need it",
  assumed: "Assumed",
  optional: "Optional",
  check: "Check this line",
};

export function lineStatus(
  line: CoreLine,
  pantry: ReadonlySet<IngredientId>,
  staples: ReadonlySet<IngredientId>,
): LineStatus {
  if (line.opt) return "optional";
  if (line.o.some((o) => staples.has(o))) return "assumed";
  if (!line.r || line.o.length === 0) return "check";
  return line.o.some((o) => pantry.has(o)) ? "have" : "missing";
}
