// Port of pantrychef/ingredients/table.py `tokens` (fold + canonicalize). Golden cases in
// tests/golden/answer_cases.json keep the two in step.

function singularize(word: string): string {
  if (word.length <= 3) return word;
  if (word.endsWith("ss")) return word;
  if (word.endsWith("sses")) return word;
  if (word.endsWith("ies")) return word.slice(0, -3) + "y";
  if (/(ches|shes|ses|xes|zes)$/.test(word)) return word.slice(0, -2);
  if (word.endsWith("oes")) return word.slice(0, -2);
  if (word.endsWith("s")) return word.slice(0, -1);
  return word;
}

function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{Mn}/gu, "");
}

export function tokens(text: string): string[] {
  const spaced = fold(text).replace(/-/g, " ");
  const norm = spaced
    .normalize("NFKC")
    .toLowerCase()
    .trim()
    .replace(/\([^)]*\)/g, " ")
    .replace(/[^a-z0-9/.\-\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return norm === "" ? [] : norm.split(" ").map(singularize);
}
