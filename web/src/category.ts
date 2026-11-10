// Which icon fits an ingredient name. The table has no category column, so this is a keyword
// heuristic. It is for decoration only: the word is always shown too, and the icon is hidden from
// screen readers. A wrong icon is worse than none, so no match means no icon. Words are matched
// whole (\b), so "eggplant" is not "egg" and "butternut" is not "butter".

export type IconKey =
  | "egg" | "dairy" | "fruit" | "root" | "veg" | "mushroom" | "herb" | "grain"
  | "bread" | "meat" | "fish" | "legume" | "bottle" | "tin" | "tofu";

// Checked first, in order. These names hold a word of another group, or are not what they seem.
const FIRST: [RegExp, IconKey | null][] = [
  [/\b(peanut|almond|cashew|nut) butter\b/, null],
  [/\bcream of tartar\b/, null],
  [/\b(coconut|condensed|evaporated) milk\b|\bcondensed soup\b|\bcanned\b|\btomato (paste|sauce)\b|\bpizza sauce\b|\bstock\b/, "tin"],
  [/\begg noodle\b/, "grain"],
  [/\b(green bean|bean sprout|butternut squash|green onion|mixed vegetables|collard greens)\b/, "veg"],
  // Spices, seeds and powders carry the word of the plant they come from.
  [/\b(seed|powder|flakes|extract|seasoning|lemon pepper|black pepper|white pepper|baking soda|mixed spice)\b/, null],
  [/^ground (?!beef|pork|turkey|lamb|chicken)/, null],
  [/\b(juice|lemonade|vinegar|honey|syrup|molasses|ketchup|mayonnaise|sauce|wine|beer|rum|brandy|vodka|whiskey|sherry|liqueur|tequila|gin|sake|mirin|club soda|oil)\b/, "bottle"],
];

// Then the first rule that matches wins. Order matters: "bread flour" is grain, not bread.
const RULES: [IconKey, RegExp][] = [
  ["tofu", /\b(tofu|tempeh)\b/],
  ["egg", /\begg\b/],
  ["dairy", /\b(milk|buttermilk|cream|yogurt|cheese|cheddar|mozzarella|parmesan|feta|ricotta|butter|margarine|half and half|monterey jack)\b/],
  ["legume", /\b(lentil|chickpea|beans?|split pea|dal)\b/],
  ["fish", /\b(salmon|tuna|white fish|shrimp|crab|lobster|clam|mussel|oyster|scallop|anchovy|sardine|crayfish|oily fish)\b/],
  ["meat", /\b(chicken|beef|pork|bacon|ham|sausage|lamb|turkey|duck|pepperoni|meat)\b/],
  ["mushroom", /\bmushroom\b/],
  ["herb", /\b(parsley|cilantro|basil|oregano|thyme|rosemary|sage|mint|dill|chive|bay leaf|tarragon|marjoram|curry leaf|pandan leaf|lemongrass|bouquet garni)\b/],
  ["grain", /\b(flour|rice|pasta|noodle|couscous|quinoa|oats|bulgur|barley|cornmeal|semolina)\b/],
  ["bread", /\b(bread|tortilla|pita|cracker|crouton|hamburger bun)\b/],
  ["root", /\b(onion|shallot|garlic|ginger|potato|carrot|beet|radish|turnip|parsnip|cassava)\b/],
  ["fruit", /\b(lemon|lime|orange|apple|banana|strawberry|blueberry|raspberry|cranberry|grape|peach|pear|pineapple|mango|cherry|plum|watermelon|melon|apricot|fig|date|tomato|bell pepper|avocado|raisin|prune)\b/],
  ["veg", /\b(spinach|kale|cabbage|broccoli|cauliflower|zucchini|eggplant|lettuce|celery|cucumber|asparagus|pea|corn|pumpkin|okra|fennel|artichoke|bok choy|watercress|arugula|leek|squash)\b/],
];

export function categoryOf(name: string): IconKey | null {
  const n = name.toLowerCase().trim();
  if (!n) return null;
  for (const [re, key] of FIRST) if (re.test(n)) return key;
  for (const [key, re] of RULES) if (re.test(n)) return key;
  return null;
}

// 24 px stroke icons, one style. These are the mockup's paths.
export const PATHS: Record<IconKey, string[]> = {
  egg: ["M12 2.5c-3.5 0-6.5 6-6.5 10.5a6.5 6.5 0 0 0 13 0C18.5 8.5 15.5 2.5 12 2.5z", "M9 14a3 3 0 0 0 2.5 2.5"],
  dairy: ["M8 3h8l2 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7l2-4z", "M6 7h12", "M10 13h4"],
  fruit: ["M12 21a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15z", "M12 6c0-2 1.5-3.2 3.5-3.2", "M9.5 9.5a3.5 3.5 0 0 0-1.5 2"],
  root: ["M12 2.5c0 3.5-5 5.5-5 11a5 5 0 0 0 10 0c0-5.5-5-7.5-5-11z", "M12 18.5V22", "M9 21.5h6"],
  veg: ["M4.5 19.5C4.5 10.5 9.5 4.5 19.5 4.5c0 9.5-5.5 15-15 15z", "M4.5 19.5l9-9"],
  mushroom: ["M3.5 12.5a8.5 7.5 0 0 1 17 0z", "M9 12.5v5a3 3 0 0 0 6 0v-5", "M8 9h.01", "M13 8h.01"],
  herb: ["M12 21V8", "M12 12c-3 0-5-2-5-5 3 0 5 2 5 5z", "M12 16c3 0 5-2 5-5-3 0-5 2-5 5z", "M12 8c0-3 1-5 3-5"],
  grain: ["M12 21V9", "M12 9C9 9 8 7 8 4c3 0 4 2 4 5z", "M12 9c3 0 4-2 4-5-3 0-4 2-4 5z", "M12 15c-3 0-4-2-4-5", "M12 15c3 0 4-2 4-5"],
  bread: ["M4 11a4 4 0 0 1 3-6h10a4 4 0 0 1 3 6v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8z", "M9 9v3", "M15 9v3"],
  meat: ["M15 4a5 5 0 1 1 0 10 5 5 0 0 1 0-10z", "M12 13l-6 6", "M4 17.5l2.5 2.5", "M6.5 15.5L4.5 17.5"],
  fish: ["M3 12c3-5 9-6 13-3l5-2v10l-5-2c-4 3-10 2-13-3z", "M8 11.5h.01"],
  legume: ["M7 5c4-3 12 2 10 8-1 4-5 7-9 6S2 9 7 5z", "M9 10c1 1 3 2 5 2"],
  bottle: ["M10 2h4v3l2 3v12a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V8l2-3V2z", "M8 13h8"],
  tin: ["M6 6h12v14H6z", "M6 9h12", "M6 17h12"],
  tofu: ["M4 9l8-4 8 4v8l-8 4-8-4V9z", "M4 9l8 4 8-4", "M12 13v8"],
};
