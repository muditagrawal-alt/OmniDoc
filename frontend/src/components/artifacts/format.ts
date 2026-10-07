/**
 * Number parsing and formatting for answer artifacts.
 *
 * Values arrive from an LLM, so they may be numbers, "1,234", "$5.2B",
 * "12.5%", "(3,400)" or junk. parseNumber() turns what it can into a finite
 * number and remembers any currency prefix / unit suffix so axes and tooltips
 * can print the value the way the source wrote it.
 */

export interface NumberUnit {
  prefix: string;
  suffix: string;
}

export const NO_UNIT: NumberUnit = { prefix: '', suffix: '' };

export interface ParsedNumber extends NumberUnit {
  value: number;
}

const MINUS = '−';

const MAGNITUDE: Record<string, number> = {
  k: 1e3,
  thousand: 1e3,
  m: 1e6,
  mm: 1e6,
  mn: 1e6,
  mil: 1e6,
  million: 1e6,
  millions: 1e6,
  b: 1e9,
  bn: 1e9,
  billion: 1e9,
  billions: 1e9,
  t: 1e12,
  tn: 1e12,
  trillion: 1e12,
  trillions: 1e12,
};

const CURRENCY_PREFIX = /^(US\$|A\$|C\$|HK\$|USD|EUR|GBP|INR|JPY|CNY|RMB|[$€£¥₹₩])\s?/i;
const CURRENCY_SYMBOL: Record<string, string> = {
  usd: '$',
  'us$': '$',
  eur: '€',
  gbp: '£',
  inr: '₹',
  jpy: '¥',
  cny: '¥',
  rmb: '¥',
};

function parseCore(s: string): number | null {
  if (/^\d+(\.\d+)?(e[+-]?\d+)?$/i.test(s) || /^\.\d+$/.test(s)) return Number(s);
  // 1,234,567.89
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) return Number(s.replace(/,/g, ''));
  // 1.234.567,89 (European grouping)
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) return Number(s.replace(/\./g, '').replace(',', '.'));
  // 12,5 (decimal comma)
  if (/^\d+,\d{1,2}$/.test(s)) return Number(s.replace(',', '.'));
  // 1 234 567 (thin/space grouping)
  if (/^\d{1,3}( \d{3})+(\.\d+)?$/.test(s)) return Number(s.replace(/ /g, ''));
  return null;
}

/** Parses a loosely formatted number. Returns null when nothing numeric is there. */
export function parseNumber(raw: unknown): ParsedNumber | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? { value: raw, prefix: '', suffix: '' } : null;
  if (typeof raw === 'bigint') return { value: Number(raw), prefix: '', suffix: '' };
  if (typeof raw !== 'string') return null;

  let s = raw
    .replace(/[−‒–—]/g, '-')
    .replace(/[   ]/g, ' ')
    .trim();
  if (!s || s.length > 40) return null;

  let negative = false;
  if (/^\(.*\)$/.test(s)) {
    negative = true;
    s = s.slice(1, -1).trim();
  }
  if (s.startsWith('-')) {
    negative = !negative;
    s = s.slice(1).trim();
  } else if (s.startsWith('+')) {
    s = s.slice(1).trim();
  }

  let prefix = '';
  const cur = s.match(CURRENCY_PREFIX);
  if (cur) {
    const sym = cur[1];
    prefix = CURRENCY_SYMBOL[sym.toLowerCase()] ?? sym.toUpperCase().replace('US$', '$');
    s = s.slice(cur[0].length).trim();
    if (s.startsWith('-')) {
      negative = !negative;
      s = s.slice(1).trim();
    }
  }

  let suffix = '';
  let multiplier = 1;
  if (s.endsWith('%')) {
    suffix = '%';
    s = s.slice(0, -1).trim();
  } else {
    const tail = s.match(/^([\d.,\s]*\d)\s*([A-Za-z$€£¥₹]{1,9})\.?$/);
    if (tail) {
      const word = tail[2];
      const mag = MAGNITUDE[word.toLowerCase()];
      if (mag) multiplier = mag;
      else if (CURRENCY_SYMBOL[word.toLowerCase()] && !prefix) prefix = CURRENCY_SYMBOL[word.toLowerCase()];
      else suffix = ` ${word}`;
      s = tail[1].trim();
    }
  }

  const core = parseCore(s);
  if (core === null || !Number.isFinite(core)) return null;
  const value = (negative ? -core : core) * multiplier;
  return Number.isFinite(value) ? { value, prefix, suffix } : null;
}

export function toNumber(raw: unknown): number | null {
  return parseNumber(raw)?.value ?? null;
}

/** The prefix/suffix that most parsed values agree on. */
export function consensusUnit(parsed: Array<ParsedNumber | null>): NumberUnit {
  const valid = parsed.filter((p): p is ParsedNumber => p !== null);
  if (!valid.length) return NO_UNIT;
  const vote = (key: 'prefix' | 'suffix') => {
    const counts = new Map<string, number>();
    valid.forEach((p) => counts.set(p[key], (counts.get(p[key]) ?? 0) + 1));
    let best = '';
    let bestN = 0;
    counts.forEach((n, k) => {
      if (k && n > bestN) {
        best = k;
        bestN = n;
      }
    });
    return bestN * 2 > valid.length ? best : '';
  };
  return { prefix: vote('prefix'), suffix: vote('suffix') };
}

/* ----------------------------------------------------------------- Ticks */

function tickStep(min: number, max: number, count: number): number {
  const raw = (max - min) / Math.max(1, count);
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const err = raw / pow;
  const mult = err >= Math.sqrt(50) ? 10 : err >= Math.sqrt(10) ? 5 : err >= Math.sqrt(2) ? 2 : 1;
  return mult * pow;
}

function clean(n: number): number {
  return Number(n.toPrecision(12));
}

export interface TickSet {
  ticks: number[];
  step: number;
  min: number;
  max: number;
}

/** Round, evenly spaced ticks covering [min, max]; the domain snaps to them. */
export function niceTicks(min: number, max: number, count: number, opts: { integer?: boolean } = {}): TickSet {
  let lo = Math.min(min, max);
  let hi = Math.max(min, max);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    lo = 0;
    hi = 1;
  }
  if (lo === hi) {
    if (lo === 0) hi = 1;
    else {
      const pad = Math.abs(lo) * 0.1;
      lo -= pad;
      hi += pad;
    }
  }
  let step = tickStep(lo, hi, count);
  if (opts.integer) step = Math.max(1, Math.round(step));
  const start = Math.floor(clean(lo / step));
  const stop = Math.ceil(clean(hi / step));
  const ticks: number[] = [];
  for (let i = start; i <= stop && ticks.length < 50; i++) ticks.push(clean(i * step));
  return { ticks, step, min: ticks[0], max: ticks[ticks.length - 1] };
}

/** Ticks strictly inside [min, max] without extending the domain (used for x on lines). */
export function innerTicks(min: number, max: number, count: number, opts: { integer?: boolean } = {}): number[] {
  if (min === max) return [min];
  let step = tickStep(min, max, count);
  if (opts.integer) step = Math.max(1, Math.round(step));
  const out: number[] = [];
  for (let i = Math.ceil(clean(min / step)); i * step <= max + step * 1e-9 && out.length < 50; i++) out.push(clean(i * step));
  return out;
}

/* ------------------------------------------------------------ Formatting */

const COMPACT: Array<[number, string]> = [
  [1e12, 'T'],
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'K'],
];

function trimZeros(s: string): string {
  if (!s.includes('.')) return s;
  const t = s.replace(/0+$/, '');
  return t.endsWith('.') ? t.slice(0, -1) : t;
}

function withUnit(body: string, negative: boolean, unit: NumberUnit): string {
  return `${negative ? MINUS : ''}${unit.prefix}${body}${unit.suffix}`;
}

function grouped(n: number, decimals: number): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: decimals });
}

/** Axis tick label. `step` is the tick spacing so neighbouring ticks never print the same text. */
export function formatTick(v: number, step: number, unit: NumberUnit = NO_UNIT, maxAbs = Math.abs(v)): string {
  if (v === 0) return withUnit('0', false, unit);
  const abs = Math.abs(v);
  const tier = COMPACT.find(([d]) => maxAbs >= d);
  if (tier && maxAbs >= 1e4) {
    const [div, sym] = tier;
    const decimals = Math.max(0, Math.min(3, Math.ceil(-Math.log10(step / div) - 1e-9)));
    return withUnit(`${trimZeros((abs / div).toFixed(decimals))}${sym}`, v < 0, unit);
  }
  const decimals = Math.max(0, Math.min(4, Math.ceil(-Math.log10(step) - 1e-9)));
  return withUnit(trimZeros(grouped(abs, decimals)), v < 0, unit);
}

/** Short, human value for tooltips and direct labels: 1,234 · 12.5K · $5.2B. */
export function formatValue(v: number | null | undefined, unit: NumberUnit = NO_UNIT): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e6) {
    const [div, sym] = COMPACT.find(([d]) => abs >= d) ?? [1, ''];
    return withUnit(`${trimZeros((abs / div).toFixed(2))}${sym}`, v < 0, unit);
  }
  const decimals = abs >= 1000 ? 1 : abs >= 1 ? 2 : abs === 0 ? 0 : 4;
  return withUnit(grouped(abs, decimals), v < 0, unit);
}

/** Precise value for the table view. */
export function formatPrecise(v: number | null | undefined, unit: NumberUnit = NO_UNIT): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e9) {
    const [div, sym] = COMPACT.find(([d]) => abs >= d) ?? [1, ''];
    return withUnit(`${trimZeros((abs / div).toFixed(3))}${sym}`, v < 0, unit);
  }
  return withUnit(grouped(abs, abs >= 1 ? 4 : 6), v < 0, unit);
}

export function formatPercent(share: number): string {
  if (!Number.isFinite(share)) return '—';
  const pct = share * 100;
  return `${pct < 10 ? pct.toFixed(1) : pct.toFixed(0)}%`;
}

/** True when every value is an integer year (1000-2999): print as-is, no grouping. */
export function looksLikeYears(values: number[]): boolean {
  return values.length > 0 && values.every((v) => Number.isInteger(v) && v >= 1000 && v <= 2999);
}

export function formatPlain(v: number, step = 1): string {
  const decimals = Math.max(0, Math.min(4, Math.ceil(-Math.log10(step) - 1e-9)));
  return `${v < 0 ? MINUS : ''}${Math.abs(v).toFixed(decimals)}`;
}
