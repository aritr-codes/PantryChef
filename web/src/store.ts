// Save the kitchen in this browser only. It stores ingredient ids and the staple switches that
// are off. It never stores typed text. Every read and write is guarded, because storage can be
// blocked (private windows, site settings). The page works the same without it.

const KEY = "pantrychef.kitchen.v1";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export interface Saved {
  ids: string[];
  staplesOff: string[];
}

export function getStorage(): Store | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** True when a write and a read-back work now. */
export function storageWorks(storage: Store | null = getStorage()): boolean {
  if (!storage) return false;
  try {
    const probe = "pantrychef.probe";
    storage.setItem(probe, "1");
    const ok = storage.getItem(probe) === "1";
    storage.removeItem(probe);
    return ok;
  } catch {
    return false;
  }
}

const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

/** The saved kitchen, or null when there is none or it is damaged. Unknown ids are dropped. */
export function load(known: ReadonlySet<string>, storage: Store | null = getStorage()): Saved | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(KEY);
    if (!raw) return null;
    const doc: unknown = JSON.parse(raw);
    if (typeof doc !== "object" || doc === null) return null;
    const d = doc as Record<string, unknown>;
    if (d.v !== 1 || !strings(d.ids) || !strings(d.staplesOff)) return null;
    return {
      ids: [...new Set(d.ids)].filter((id) => known.has(id)),
      staplesOff: [...new Set(d.staplesOff)].filter((id) => known.has(id)),
    };
  } catch {
    return null;
  }
}

/** Returns false when the write failed. */
export function save(s: Saved, storage: Store | null = getStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(KEY, JSON.stringify({ v: 1, ids: s.ids, staplesOff: s.staplesOff }));
    return true;
  } catch {
    return false;
  }
}
