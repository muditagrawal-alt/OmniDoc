import { formatTick, formatValue, innerTicks, niceTicks } from './format';
import { clamp, linearScale } from './geometry';
import type { Scale } from './geometry';
import { fitText, font, measureText } from './hooks';
import type { NormChart } from './normalize';

export interface XYTick {
  pos: number;
  text: string;
  zero?: boolean;
}

export interface XYLayout {
  width: number;
  height: number;
  plot: { x: number; y: number; w: number; h: number };
  x: Scale;
  y: Scale;
  xTicks: XYTick[];
  yTicks: XYTick[];
  /** Pixel y of the value baseline (zero when in range, else the bottom). */
  baseY: number;
  zeroInDomain: boolean;
  titles: Array<{ x: number; y: number; text: string; anchor: 'start' | 'middle' | 'end' }>;
}

export function xLabel(chart: NormChart, x: number): string {
  if (chart.xKind === 'category') return chart.categories[Math.round(x)] ?? '';
  if (chart.xKind === 'year') return String(x);
  return formatValue(x, chart.xUnit);
}

export function layoutXY(
  chart: NormChart,
  width: number,
  height: number,
  vis: number[],
  kind: 'line' | 'scatter',
  rightPadFor: (y: Scale, plotTop: number, plotBottom: number) => number,
): XYLayout | null {
  const pts = vis.flatMap((s) => chart.points[s] ?? []);
  if (!pts.length || width < 80) return null;
  const fTick = font('mono', 11);
  const fCat = font('ui', 12);
  const fTitle = font('ui', 11, 500);

  /* ---- y */
  let lo = Math.min(...pts.map((p) => p.y));
  let hi = Math.max(...pts.map((p) => p.y));
  if (kind === 'line') {
    if (lo > 0 && lo <= hi * 0.5) lo = 0;
    if (hi < 0 && hi >= lo * 0.5) hi = 0;
  }
  const top = chart.yTitle ? 26 : 10;
  const bottom = 24 + (chart.xTitle ? 18 : 0);
  const plotH = Math.max(60, height - top - bottom);
  const yt = niceTicks(lo, hi, clamp(Math.round(plotH / 44), 2, 8));
  const yMaxAbs = Math.max(Math.abs(yt.min), Math.abs(yt.max));
  const yTexts = yt.ticks.map((v) => formatTick(v, yt.step, chart.unit, yMaxAbs));
  const left = Math.ceil(Math.max(...yTexts.map((t) => measureText(t, fTick)))) + 12;
  const y = linearScale(yt.min, yt.max, top + plotH, top);
  const yTicks = yt.ticks.map((v, i) => ({ pos: y(v), text: yTexts[i], zero: v === 0 }));
  const zeroInDomain = yt.min <= 0 && yt.max >= 0;
  const baseY = zeroInDomain ? y(0) : top + plotH;

  /* ---- x */
  const right = Math.max(8, rightPadFor(y, top, top + plotH));
  const plotW = Math.max(40, width - left - right);
  let x: Scale;
  let xTicks: XYTick[] = [];

  if (chart.xKind === 'category') {
    const n = chart.categories.length;
    const d0 = kind === 'scatter' || n === 1 ? -0.5 : 0;
    const d1 = kind === 'scatter' || n === 1 ? n - 0.5 : n - 1;
    x = linearScale(d0, d1, left, left + plotW);
    const widths = chart.categories.map((c) => measureText(c, fCat));
    const spacing = plotW / Math.max(1, d1 - d0);
    const maxW = Math.min(Math.max(...widths), 160);
    const every = Math.max(1, Math.ceil((maxW + 14) / spacing));
    const room = Math.max(24, spacing * every - 10);
    for (let i = 0; i < n; i += every) {
      const text = fitText(chart.categories[i], room, fCat);
      const w = measureText(text, fCat);
      xTicks.push({ pos: clamp(x(i), w / 2, width - w / 2), text });
    }
  } else {
    const xs = pts.map((p) => p.x);
    let x0 = Math.min(...xs);
    let x1 = Math.max(...xs);
    const integer = chart.xKind === 'year';
    const count = clamp(Math.round(plotW / 92), 2, 8);
    let ticks: number[];
    let step: number;
    if (kind === 'scatter') {
      const t = niceTicks(x0, x1, count, { integer });
      x0 = t.min;
      x1 = t.max;
      ticks = t.ticks;
      step = t.step;
    } else {
      if (x0 === x1) {
        x0 -= 1;
        x1 += 1;
      }
      ticks = innerTicks(x0, x1, count, { integer });
      step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    }
    x = linearScale(x0, x1, left, left + plotW);
    const maxAbs = Math.max(Math.abs(x0), Math.abs(x1));
    xTicks = ticks.map((v) => {
      const text = chart.xKind === 'year' ? String(v) : formatTick(v, step, chart.xUnit, maxAbs);
      const w = measureText(text, fTick);
      return { pos: clamp(x(v), w / 2, width - w / 2), text };
    });
    // Drop ticks whose labels would touch.
    xTicks = xTicks.filter((t, i, all) => i === 0 || t.pos - all[i - 1].pos > measureText(t.text, fTick) + 10);
  }

  const titles: XYLayout['titles'] = [];
  if (chart.yTitle) titles.push({ x: 0, y: 12, text: fitText(chart.yTitle, width * 0.7, fTitle), anchor: 'start' });
  if (chart.xTitle) titles.push({ x: left + plotW / 2, y: top + plotH + 38, text: fitText(chart.xTitle, plotW, fTitle), anchor: 'middle' });

  return {
    width,
    height: Math.ceil(top + plotH + bottom),
    plot: { x: left, y: top, w: plotW, h: plotH },
    x,
    y,
    xTicks,
    yTicks,
    baseY,
    zeroInDomain,
    titles,
  };
}
