/**
 * Entity categories come from LLM extraction and are free-form ("Method",
 * "Architectural Component", "Limitation", ...). For colour we fold them into
 * seven stable families plus "Other", mapped in a fixed order onto the
 * validated categorical palette (--cat-1 ... --cat-7). Colour follows the
 * family, never its rank, so filtering never repaints the survivors.
 */

export interface CategoryFamily {
  key: string;
  label: string;
  cssVar: string;
  match: RegExp;
}

export const FAMILIES: CategoryFamily[] = [
  { key: 'org', label: 'Organizations', cssVar: '--cat-1', match: /organi[sz]ation|company|corp|institut|agency|university|fund|bank|government|team|lab\b/i },
  { key: 'person', label: 'People', cssVar: '--cat-2', match: /person|people|author|founder|ceo|researcher|executive|employee|role/i },
  {
    key: 'tech',
    label: 'Technology & resources',
    cssVar: '--cat-3',
    match:
      /tech|component|model|system|software|hardware|framework|architecture|tool|platform|application|product|device|infrastructure|facilit|equipment|machine|vehicle|energy source|natural source|renewable|fuel|resource|material|substance|chemical/i,
  },
  {
    key: 'metric',
    label: 'Metrics & quantities',
    cssVar: '--cat-4',
    match: /metric|data|number|measure|statistic|financ|value|kpi|amount|revenue|cost|price|rate|quantity|demand|consumption|capacity|distance|percent|ratio/i,
  },
  {
    key: 'method',
    label: 'Methods & concepts',
    cssVar: '--cat-5',
    match: /method|concept|technique|algorithm|approach|process|theory|field|principle|strategy|idea|topic|factor|proposal|goal|objective|\baction/i,
  },
  { key: 'place', label: 'Places & events', cssVar: '--cat-6', match: /location|place|country|city|region|geo|address|event|date|time|period|year|histor/i },
  {
    key: 'doc',
    label: 'Documents & issues',
    cssVar: '--cat-7',
    match: /document|claim|regulation|policy|law|clause|limitation|content|standard|requirement|risk|finding|section|publication|media|study|report|issue|impact|problem|challenge/i,
  },
];

export const OTHER_FAMILY: CategoryFamily = {
  key: 'other',
  label: 'Other',
  cssVar: '--cat-other',
  match: /.^/,
};

const cache = new Map<string, CategoryFamily>();

export function familyOf(category: string | undefined | null): CategoryFamily {
  const key = (category || '').trim();
  const hit = cache.get(key);
  if (hit) return hit;
  const fam = FAMILIES.find((f) => f.match.test(key)) ?? OTHER_FAMILY;
  cache.set(key, fam);
  return fam;
}

export const ALL_FAMILIES: CategoryFamily[] = [...FAMILIES, OTHER_FAMILY];
