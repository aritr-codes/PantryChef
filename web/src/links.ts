// Source links come from the pack. Only https://en.wikibooks.org/ links may become <a href>.
// The pack builder checks this too (pantrychef/pack/build.py: check_source_url).

export function safeWikibooksUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:" || u.hostname !== "en.wikibooks.org") return null;
    if (u.username || u.password || u.port) return null;
    return u.href;
  } catch {
    return null;
  }
}

/** The page-history link, where the authors are listed. */
export function historyUrl(pageUrl: string): string | null {
  const safe = safeWikibooksUrl(pageUrl);
  if (!safe) return null;
  const u = new URL(safe);
  u.searchParams.set("action", "history");
  return u.href;
}
