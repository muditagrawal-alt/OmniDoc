/**
 * Defensive normalisation of answer artifacts.
 *
 * The visualization agent emits a Plotly-shaped spec, but stored messages
 * span several generations: some only carry `underlying_data`, titles may be
 * `{ text }` objects, numbers may be strings ("1,234", "$5.2B"), traces may be
 * empty. Everything here returns a plain, render-ready structure and never
 * throws; an artifact with nothing plottable comes back with `empty: true`.
 */

import type { ChartArtifact, ChartTrace, MathResult } from '../../api';
import { consensusUnit, looksLikeYears, NO_UNIT, parseNumber, toNumber } from './format';
import type { NumberUnit, ParsedNumber } from './format';

export type ChartForm = 'bar' | 'line' | 'scatter' | 'donut';

/** Categorical slots in fixed order; never cycled. */
export const CAT_SLOTS = 7;
/** All-pairs forms (scatter) validate only the first three slots. */
export const SCATTER_SLOTS = 3;
export const DONUT_MAX = 6;

export interface NormSeries {
  name: string;
  /** CSS colour reference, e.g. `var(--cat-2)`. */
  color: string;
  other: boolean;
}

export interface XYPoint {
  x: number;
  y: number;
  label?: string;
}

export interface TableModel {
  columns: string[];
  /** First cell is the row label; the rest are numbers (or null). */
  rows: Array<[string, ...Array<number | null>]>;
  numericFrom: number;
}

export interface NormChart {
  form: ChartForm;
  requested: string;
  title: string;
  caption: string;
  xTitle: string;
  yTitle: string;
  unit: NumberUnit;
  xUnit: NumberUnit;
  series: NormSeries[];
  /** bar / donut: category labels. line / scatter with categorical x: labels by index. */
  categories: string[];
  /** bar / donut: values[series][category]. */
  values: Array<Array<number | null>>;
  /** line / scatter: points[series], sorted by x for lines. */
  points: XYPoint[][];
  xKind: 'category' | 'number' | 'year';
  /** A pie with too many (or too few) slices, shown as ranked bars. */
  fromPie: boolean;
  preferHorizontal: boolean;
  table: TableModel;
  sourceNs: number[];
  empty: boolean;
}

/* --------------------------------------------------------------- helpers */

type Rec = Record<string, unknown>;

function isRec(v: unknown): v is Rec {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Accepts "Title", { text: "Title" }, numbers; anything else becomes ''. */
export function textOf(v: unknown): string {
  if (typeof v === 'string') return v.trim();
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  if (isRec(v)) return textOf(v.text ?? v.title ?? v.label ?? v.name);
  return '';
}

function labelOf(v: unknown, index: number): string {
  if (typeof v === 'string') return v.trim() || '(blank)';
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (isRec(v)) return textOf(v) || `Item ${index + 1}`;
  return v === null || v === undefined ? '(blank)' : String(v);
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key;
}

export function slotColor(index: number, slots: number): string {
  return index < slots ? `var(--cat-${index + 1})` : 'var(--cat-other)';
}

/* -------------------------------------------------------- raw extraction */

interface RawSeries {
  name: string;
  xs: unknown[];
  ys: ParsedNumberOrNull[];
  mode: string;
  type: string;
}

type ParsedNumberOrNull = ParsedNumber | null;

interface RawPie {
  labels: string[];
  values: ParsedNumberOrNull[];
}

const LABEL_KEYS = ['label', 'name', 'category', 'x', 'year', 'date', 'period', 'month', 'quarter', 'group', 'segment', 'item', 'key'];
const VALUE_KEYS = ['value', 'y', 'amount', 'count', 'total', 'val'];

function tracesOf(chart: ChartArtifact): ChartTrace[] {
  const spec: unknown = chart.plotly_spec;
  if (!isRec(spec)) return [];
  return arr(spec.data).filter(isRec) as ChartTrace[];
}

function seriesFromTraces(traces: ChartTrace[], yTitle: string): RawSeries[] {
  const out: RawSeries[] = [];
  traces.forEach((t, i) => {
    const tr = t as Rec;
    const type = str(tr.type).toLowerCase();
    if (type === 'pie') return;
    const horizontal = str(tr.orientation) === 'h';
    let xs = arr(horizontal ? tr.y : tr.x);
    const ysRaw = arr(horizontal ? tr.x : tr.y);
    if (!ysRaw.length) return;
    if (!xs.length) xs = ysRaw.map((_, k) => k + 1);
    const n = Math.min(xs.length, ysRaw.length);
    const name = textOf(tr.name) || (traces.length === 1 ? yTitle || 'Value' : `Series ${i + 1}`);
    out.push({
      name,
      xs: xs.slice(0, n),
      ys: ysRaw.slice(0, n).map(parseNumber),
      mode: str(tr.mode).toLowerCase(),
      type,
    });
  });
  return out.filter((s) => s.ys.some((y) => y !== null));
}

function pieFromTraces(traces: ChartTrace[]): RawPie | null {
  for (const t of traces) {
    const tr = t as Rec;
    const labels = arr(tr.labels);
    const values = arr(tr.values);
    if (labels.length && values.length) {
      const n = Math.min(labels.length, values.length);
      return { labels: labels.slice(0, n).map(labelOf), values: values.slice(0, n).map(parseNumber) };
    }
  }
  return null;
}

interface RowExtraction {
  labelKey: string | null;
  series: RawSeries[];
}

function seriesFromRows(rowsIn: unknown, yTitle: string, wantScatter: boolean): RowExtraction {
  const rows = arr(rowsIn).filter(isRec);
  if (!rows.length) return { labelKey: null, series: [] };

  const keys: string[] = [];
  rows.forEach((r) => Object.keys(r).forEach((k) => keys.includes(k) || keys.push(k)));
  const lower = new Map(keys.map((k) => [k.toLowerCase(), k]));
  const numericShare = (k: string) => rows.filter((r) => parseNumber(r[k]) !== null).length / rows.length;

  const explicitValue = VALUE_KEYS.map((k) => lower.get(k)).find((k) => k !== undefined && numericShare(k) > 0);
  let labelKey =
    LABEL_KEYS.map((k) => lower.get(k)).find((k) => k !== undefined && k !== explicitValue && rows.some((r) => r[k] !== undefined)) ?? null;
  if (!labelKey) labelKey = keys.find((k) => k !== explicitValue && numericShare(k) < 0.5) ?? null;

  let valueKeys: string[];
  if (explicitValue) valueKeys = [explicitValue];
  else valueKeys = keys.filter((k) => k !== labelKey && numericShare(k) >= 0.5).slice(0, 12);

  // A scatter with no label column: first numeric column is x, the rest are y.
  if (wantScatter && !labelKey && valueKeys.length >= 2) {
    const [xKey, ...yKeys] = valueKeys;
    return {
      labelKey: xKey,
      series: yKeys.map((k) => ({
        name: humanize(k),
        xs: rows.map((r) => r[xKey]),
        ys: rows.map((r) => parseNumber(r[k])),
        mode: 'markers',
        type: 'scatter',
      })),
    };
  }

  const xs = rows.map((r, i) => (labelKey ? r[labelKey] : i + 1));
  return {
    labelKey,
    series: valueKeys
      .map((k) => ({
        name: valueKeys.length === 1 ? yTitle || (k === explicitValue ? 'Value' : humanize(k)) : humanize(k),
        xs,
        ys: rows.map((r) => parseNumber(r[k])),
        mode: '',
        type: '',
      }))
      .filter((s) => s.ys.some((y) => y !== null)),
  };
}

/* ---------------------------------------------------------------- forms */

function resolveForm(requested: string, traces: ChartTrace[]): 'bar' | 'line' | 'scatter' | 'pie' {
  const types = traces.map((t) => str((t as Rec).type).toLowerCase());
  const modes = traces.map((t) => str((t as Rec).mode).toLowerCase());
  if (requested === 'pie' || requested === 'donut' || (types.includes('pie') && requested !== 'bar')) return 'pie';
  if (requested === 'line' || requested === 'area') return 'line';
  if (requested === 'scatter') return modes.some((m) => m.includes('lines')) ? 'line' : 'scatter';
  if (requested === 'bar' || requested === 'column' || requested === 'histogram') return 'bar';
  if (types.includes('line') || (types.includes('scatter') && modes.some((m) => m.includes('lines')))) return 'line';
  if (types.includes('scatter')) return 'scatter';
  return 'bar';
}

function mergeCategories(series: RawSeries[]): { categories: string[]; values: Array<Array<number | null>> } {
  const categories: string[] = [];
  const index = new Map<string, number>();
  series.forEach((s) =>
    s.xs.forEach((x, i) => {
      const label = labelOf(x, i);
      if (!index.has(label)) {
        index.set(label, categories.length);
        categories.push(label);
      }
    }),
  );
  const values = series.map((s) => {
    const row: Array<number | null> = new Array<number | null>(categories.length).fill(null);
    const seen = new Set<number>();
    s.xs.forEach((x, i) => {
      const c = index.get(labelOf(x, i));
      if (c === undefined || seen.has(c)) return;
      seen.add(c);
      row[c] = s.ys[i]?.value ?? null;
    });
    return row;
  });
  return { categories, values };
}

function foldCategorical(
  series: NormSeries[],
  values: Array<Array<number | null>>,
  slots: number,
): { series: NormSeries[]; values: Array<Array<number | null>> } {
  if (series.length <= slots) return { series, values };
  const keep = series.slice(0, slots);
  const rest = values.slice(slots);
  const folded = values[0].map((_, c) => {
    let sum: number | null = null;
    rest.forEach((row) => {
      const v = row[c];
      if (v !== null) sum = (sum ?? 0) + v;
    });
    return sum;
  });
  return {
    series: [...keep, { name: `Other (${series.length - slots})`, color: 'var(--cat-other)', other: true }],
    values: [...values.slice(0, slots), folded],
  };
}

function emptyChart(chart: ChartArtifact, base: Partial<NormChart>): NormChart {
  return {
    form: 'bar',
    requested: str(chart.chart_type),
    title: '',
    caption: '',
    xTitle: '',
    yTitle: '',
    unit: NO_UNIT,
    xUnit: NO_UNIT,
    series: [],
    categories: [],
    values: [],
    points: [],
    xKind: 'category',
    fromPie: false,
    preferHorizontal: false,
    table: { columns: [], rows: [], numericFrom: 1 },
    sourceNs: [],
    empty: true,
    ...base,
  };
}

function categoricalTable(firstCol: string, categories: string[], series: Array<{ name: string }>, values: Array<Array<number | null>>): TableModel {
  return {
    columns: [firstCol, ...series.map((s) => s.name)],
    rows: categories.map((c, i) => [c, ...values.map((row) => row[i] ?? null)] as [string, ...Array<number | null>]),
    numericFrom: 1,
  };
}

/** Legacy rows sometimes carry `unit: "$ Billion"`; when every row agrees it names the value axis. */
function unitColumn(rowsIn: unknown): string {
  const units = new Set(
    arr(rowsIn)
      .filter(isRec)
      .map((r) => textOf(r.unit ?? r.units)),
  );
  if (units.size !== 1) return '';
  return [...units][0];
}

/** Turns any stored chart artifact into a render-ready model. Never throws. */
export function normalizeChart(chart: ChartArtifact | null | undefined): NormChart {
  const safe: ChartArtifact = isRec(chart) ? chart : { chart_type: 'bar', title: '' };
  try {
    return normalizeUnsafe(safe);
  } catch {
    return emptyChart(safe, { title: textOf(safe.title) || 'Chart' });
  }
}

function normalizeUnsafe(chart: ChartArtifact): NormChart {
  const spec: unknown = chart.plotly_spec;
  const layout: Rec = isRec(spec) && isRec(spec.layout) ? spec.layout : {};
  const xTitle = textOf(isRec(layout.xaxis) ? layout.xaxis.title : undefined);
  const yTitle = textOf(isRec(layout.yaxis) ? layout.yaxis.title : undefined) || unitColumn(chart.underlying_data);
  const title = textOf(chart.title) || textOf(layout.title) || 'Untitled chart';
  const caption = textOf(chart.caption);
  const requested = str(chart.chart_type).toLowerCase().trim();
  const sourceNs = arr(chart.source_ns)
    .map(toNumber)
    .filter((n): n is number => n !== null && Number.isInteger(n) && n > 0);
  const traces = tracesOf(chart);
  const form = resolveForm(requested, traces);
  const base = { title, caption, xTitle, yTitle, requested, sourceNs };

  /* ---- pie / donut */
  if (form === 'pie') {
    let pie = pieFromTraces(traces);
    if (!pie) {
      const fromTraces = seriesFromTraces(traces, yTitle);
      const src = fromTraces.length ? fromTraces : seriesFromRows(chart.underlying_data, yTitle, false).series;
      if (src.length) pie = { labels: src[0].xs.map(labelOf), values: src[0].ys };
    }
    if (!pie || !pie.values.some((v) => v !== null)) {
      const rows = seriesFromRows(chart.underlying_data, yTitle, false).series;
      if (rows.length) pie = { labels: rows[0].xs.map(labelOf), values: rows[0].ys };
    }
    if (!pie) return emptyChart(chart, base);
    const pairs = pie.labels
      .map((label, i) => ({ label, value: pie.values[i]?.value ?? null }))
      .filter((p): p is { label: string; value: number } => p.value !== null);
    if (!pairs.length) return emptyChart(chart, base);
    const unit = consensusUnit(pie.values);
    const valueName = yTitle || 'Value';
    const allPositive = pairs.every((p) => p.value >= 0) && pairs.some((p) => p.value > 0);
    const asDonut = allPositive && pairs.length >= 3 && pairs.length <= DONUT_MAX;
    const ordered = asDonut ? pairs : [...pairs].sort((a, b) => b.value - a.value);
    const categories = ordered.map((p) => p.label);
    const values = [ordered.map((p) => p.value)];
    return {
      ...emptyChart(chart, base),
      form: asDonut ? 'donut' : 'bar',
      unit,
      series: [{ name: valueName, color: 'var(--cat-1)', other: false }],
      categories,
      values,
      fromPie: !asDonut,
      preferHorizontal: !asDonut,
      table: categoricalTable(xTitle || 'Category', categories, [{ name: valueName }], values),
      empty: false,
    };
  }

  /* ---- series-shaped forms */
  let raw = seriesFromTraces(traces, yTitle);
  let labelKey: string | null = null;
  if (!raw.length) {
    const fromRows = seriesFromRows(chart.underlying_data, yTitle, form === 'scatter');
    raw = fromRows.series;
    labelKey = fromRows.labelKey;
  }
  if (!raw.length) return emptyChart(chart, base);

  const unit = consensusUnit(raw.flatMap((s) => s.ys));
  const firstCol = xTitle || (labelKey ? humanize(labelKey) : 'Category');
  const preferHorizontal = traces.some((t) => str((t as Rec).orientation) === 'h');

  if (form === 'bar') {
    const { categories, values } = mergeCategories(raw);
    const named = raw.map((s, i) => ({ name: s.name, color: slotColor(i, CAT_SLOTS), other: false }));
    const folded = foldCategorical(named, values, CAT_SLOTS);
    if (named.length === 1) folded.series[0].color = 'var(--cat-1)';
    return {
      ...emptyChart(chart, base),
      form: 'bar',
      unit,
      series: folded.series,
      categories,
      values: folded.values,
      preferHorizontal,
      table: categoricalTable(firstCol, categories, named, values),
      empty: false,
    };
  }

  // line / scatter: decide whether x is numeric
  const xParsed = raw.flatMap((s) => s.xs.map(parseNumber));
  const xNumeric = xParsed.length > 0 && xParsed.every((p) => p !== null);
  const xNums = xParsed.filter((p): p is ParsedNumber => p !== null).map((p) => p.value);
  const xKind: NormChart['xKind'] = xNumeric ? (looksLikeYears(xNums) ? 'year' : 'number') : 'category';
  const xUnit = xNumeric ? consensusUnit(xParsed) : NO_UNIT;

  let categories: string[] = [];
  let points: XYPoint[][];
  if (xNumeric) {
    points = raw.map((s) =>
      s.xs
        .map((x, i) => {
          const xv = parseNumber(x)?.value;
          const yv = s.ys[i]?.value;
          return xv === undefined || yv === undefined ? null : { x: xv, y: yv };
        })
        .filter((p): p is XYPoint => p !== null),
    );
  } else {
    const merged = mergeCategories(raw);
    categories = merged.categories;
    points = merged.values.map((row) =>
      row.map((y, i): XYPoint | null => (y === null ? null : { x: i, y, label: categories[i] })).filter((p): p is XYPoint => p !== null),
    );
  }

  const slots = form === 'scatter' ? SCATTER_SLOTS : CAT_SLOTS;
  let series: NormSeries[] = raw.map((s, i) => ({ name: s.name, color: slotColor(i, slots), other: false }));

  // Table keeps every original series, before folding.
  let table: TableModel;
  if (form === 'scatter' && xNumeric) {
    table = {
      columns: ['Series', xTitle || 'x', yTitle || 'y'],
      rows: raw.flatMap((s, si) => points[si].map((p) => [s.name, p.x, p.y] as [string, number, number])),
      numericFrom: 1,
    };
  } else if (xNumeric) {
    const xsAll = [...new Set(points.flatMap((ps) => ps.map((p) => p.x)))].sort((a, b) => a - b);
    table = {
      columns: [xTitle || (labelKey ? humanize(labelKey) : 'x'), ...raw.map((s) => s.name)],
      rows: xsAll.map((x) => [String(x), ...points.map((ps) => ps.find((p) => p.x === x)?.y ?? null)] as [string, ...Array<number | null>]),
      numericFrom: 1,
    };
  } else {
    table = categoricalTable(firstCol, categories, raw, mergeCategories(raw).values);
  }

  if (series.length > slots) {
    const keep = points.slice(0, slots);
    const rest = points.slice(slots);
    let other: XYPoint[];
    if (form === 'scatter') other = rest.flat();
    else {
      const byX = new Map<number, number>();
      rest.flat().forEach((p) => byX.set(p.x, (byX.get(p.x) ?? 0) + p.y));
      other = [...byX.entries()].map(([x, y]) => ({ x, y, label: categories[x] }));
    }
    points = [...keep, other];
    series = [...series.slice(0, slots), { name: `Other (${raw.length - slots})`, color: 'var(--cat-other)', other: true }];
  }
  if (form === 'line') points = points.map((ps) => [...ps].sort((a, b) => a.x - b.x));
  if (raw.length === 1) series[0].color = 'var(--cat-1)';

  return {
    ...emptyChart(chart, base),
    form,
    unit,
    xUnit,
    series,
    categories,
    points,
    xKind,
    table,
    empty: points.every((ps) => ps.length === 0),
  };
}

export function formLabel(n: Pick<NormChart, 'form' | 'fromPie' | 'series'>): string {
  if (n.fromPie) return 'Ranked bars';
  if (n.form === 'donut') return 'Donut chart';
  if (n.form === 'line') return 'Line chart';
  if (n.form === 'scatter') return 'Scatter plot';
  return n.series.length > 1 ? 'Grouped bar chart' : 'Bar chart';
}

/* ------------------------------------------------------------------ math */

export interface NormMath {
  task: string;
  formula: string;
  result: string;
  units: string;
  inputs: Array<[string, string]>;
  assumptions: string[];
  code: string;
  steps: string[];
  legacy: boolean;
}

function displayValue(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return formatMathNumber(v);
  if (typeof v === 'string') return v.trim();
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export function formatMathNumber(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs !== 0 && (abs >= 1e15 || abs < 1e-6)) {
    const [m, e] = v.toExponential(6).split('e');
    return `${m.replace(/\.?0+$/, '')} × 10^${Number(e)}`;
  }
  return v.toLocaleString('en-US', { maximumFractionDigits: abs >= 1 ? 6 : 10 }).replace('-', '−');
}

export function normalizeMath(result: MathResult | null | undefined): NormMath {
  const r: Rec = isRec(result) ? (result as unknown as Rec) : {};
  const legacy = !('task' in r) && ('expression' in r || 'result' in r);
  const formula = textOf(r.formula) || textOf(r.expression) || '';
  const task = textOf(r.task) || textOf(r.description) || textOf(r.name) || (formula ? 'Calculation' : 'Computation');
  const resultRaw = r.exact_result ?? r.result ?? r.value;
  const units = textOf(r.units) || textOf(r.unit);
  const inputs: Array<[string, string]> = isRec(r.inputs)
    ? Object.entries(r.inputs).map(([k, v]) => [k, displayValue(v)])
    : arr(r.inputs).filter(isRec).map((v, i) => [textOf(v.name) || `Input ${i + 1}`, displayValue(v.value)]);
  const assumptions = arr(r.assumptions)
    .map((a) => displayValue(a))
    .filter(Boolean);
  const stepsRaw = r.steps;
  const steps = typeof stepsRaw === 'string' ? stepsRaw.split('\n').map((s) => s.trim()).filter(Boolean) : arr(stepsRaw).map(displayValue).filter(Boolean);
  return {
    task,
    formula,
    result: displayValue(resultRaw),
    units,
    inputs,
    assumptions,
    code: typeof r.code_executed === 'string' ? r.code_executed.trim() : typeof r.code === 'string' ? r.code.trim() : '',
    steps,
    legacy,
  };
}
