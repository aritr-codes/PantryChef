// Which values are new since the last render, for short entry animations. A value stays "recent"
// for `ms`, even if the page renders again. Nothing here runs a timer or touches focus. The CSS
// only animates inside prefers-reduced-motion: no-preference, so with reduced motion the class is
// set but nothing moves. `scope` resets the memory (for example when the tab changes).

import { useRef } from "preact/hooks";

export function useRecent<T>(values: readonly T[], ms = 700, scope: unknown = null): ReadonlySet<T> {
  const seen = useRef<Set<T> | null>(null);
  const until = useRef(new Map<T, number>());
  const lastScope = useRef(scope);
  const now = Date.now();
  if (lastScope.current !== scope) {
    lastScope.current = scope;
    seen.current = null;
    until.current.clear();
  }
  if (seen.current) {
    for (const v of values) if (!seen.current.has(v)) until.current.set(v, now + ms);
  }
  seen.current = new Set(values);
  return new Set(values.filter((v) => (until.current.get(v) ?? 0) > now));
}
