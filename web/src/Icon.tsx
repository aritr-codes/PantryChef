import { PATHS, categoryOf } from "./category";

/** A decorative category icon. It shows nothing when the name matches no category. */
export function Icon(p: { name: string }) {
  const key = categoryOf(p.name);
  if (!key) return null;
  return (
    <svg class="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {PATHS[key].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
