import { useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import styles from './ChartFigure.module.css';
import { ChartTooltip, LiveRegion } from './ChartParts';
import type { TipState } from './ChartParts';
import { formatPercent, formatTick, formatValue, niceTicks } from './format';
import { barPath, clamp, linearScale } from './geometry';
import { fitText, font, measureText, useFontsVersion } from './hooks';
import type { NormChart } from './normalize';
import { stepKey } from './plotTypes';
import type { PlotProps } from './plotTypes';

const GAP = 2;
const MAX_BAR = 24;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface BarMark {
  c: number;
  s: number;
  v: number;
  d: string;
  anchor: { x: number; y: number };
  hit: Rect;
  label?: { x: number; y: number; text: string; anchor: 'start' | 'middle' | 'end' };
}

interface AxisTick {
  pos: number;
  text: string;
  zero: boolean;
}

interface BarLayout {
  horizontal: boolean;
  width: number;
  height: number;
  plot: Rect;
  ticks: AxisTick[];
  showAxis: boolean;
  zero: number;
  cats: Array<{ x: number; y: number; text: string; anchor: 'start' | 'middle' }>;
  marks: BarMark[];
  titles: Array<{ x: number; y: number; text: string; anchor: 'start' | 'middle' | 'end' }>;
}

function layoutBars(chart: NormChart, width: number, height: number, visible: boolean[], _fontsVersion: number): BarLayout | null {
  const vis = chart.series.map((_, i) => i).filter((i) => visible[i]);
  const n = chart.categories.length;
  if (!n || !vis.length || width < 60) return null;

  const fTick = font('mono', 11);
  const fCat = font('ui', 12);
  const fTitle = font('ui', 11, 500);
  const values = vis.flatMap((s) => chart.values[s]).filter((v): v is number => v !== null);
  if (!values.length) return null;
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const k = vis.length;
  const single = k === 1;
  const catWidths = chart.categories.map((c) => measureText(c, fCat));
  const maxCatW = Math.max(...catWidths);
  const estBand = (width - 48) / n;
  const horizontal = chart.preferHorizontal || n > 8 || maxCatW > estBand - 10;
  const valueText = (v: number) => formatValue(v, chart.unit);
  const marks: BarMark[] = [];
  const titles: BarLayout['titles'] = [];

  if (!horizontal) {
    const head = chart.yTitle ? 22 : 6;
    const catRow = 24;
    const foot = catRow + (chart.xTitle ? 18 : 0);
    const band0 = (width - 8) / n;
    const capLabels =
      single && n <= 12 && chart.values[vis[0]].every((v) => v === null || measureText(valueText(v), fTick) <= band0 - 6);
    const top = head + (capLabels && hi > 0 ? 16 : 4);
    const plotH = Math.max(60, height - top - foot - (capLabels && lo < 0 ? 16 : 0));

    let dMin = lo;
    let dMax = hi;
    let ticks: AxisTick[] = [];
    let left = 2;
    if (!capLabels) {
      const t = niceTicks(lo, hi, clamp(Math.round(plotH / 44), 2, 8));
      dMin = t.min;
      dMax = t.max;
      const maxAbs = Math.max(Math.abs(t.min), Math.abs(t.max));
      const texts = t.ticks.map((v) => formatTick(v, t.step, chart.unit, maxAbs));
      left = Math.ceil(Math.max(...texts.map((s) => measureText(s, fTick)))) + 12;
      const y = linearScale(t.min, t.max, top + plotH, top);
      ticks = t.ticks.map((v, i) => ({ pos: y(v), text: texts[i], zero: v === 0 }));
    }
    if (dMin === dMax) dMax = dMin + 1;
    const right = 4;
    const plotW = width - left - right;
    const y = linearScale(dMin, dMax, top + plotH, top);
    const band = plotW / n;
    const barW = Math.max(2, Math.min(MAX_BAR, (band * 0.62 - GAP * (k - 1)) / k));
    const groupW = barW * k + GAP * (k - 1);
    const y0 = y(0);

    chart.categories.forEach((_, c) => {
      vis.forEach((s, j) => {
        const v = chart.values[s][c];
        if (v === null) return;
        const x0 = left + band * c + (band - groupW) / 2 + j * (barW + GAP);
        const yv = y(v);
        const t = Math.min(yv, y0);
        const h = Math.abs(yv - y0);
        marks.push({
          c,
          s,
          v,
          d: barPath(x0, t, barW, h, v >= 0 ? 'top' : 'bottom'),
          anchor: { x: x0 + barW / 2, y: yv },
          hit: single
            ? { x: left + band * c, y: top - 16, w: band, h: plotH + 16 + catRow }
            : { x: left + band * c + (band / k) * j, y: top, w: band / k, h: plotH + catRow },
          label: capLabels
            ? { x: x0 + barW / 2, y: v >= 0 ? yv - 7 : yv + 15, text: valueText(v), anchor: 'middle' }
            : undefined,
        });
      });
    });

    const cats = chart.categories.map((cat, c) => ({
      x: left + band * (c + 0.5),
      y: top + plotH + (capLabels && lo < 0 ? 16 : 0) + 16,
      text: fitText(cat, band - 6, fCat),
      anchor: 'middle' as const,
    }));
    if (chart.yTitle) titles.push({ x: 0, y: 12, text: fitText(chart.yTitle, width * 0.7, fTitle), anchor: 'start' });
    if (chart.xTitle) titles.push({ x: left + plotW / 2, y: height - 4, text: fitText(chart.xTitle, plotW, fTitle), anchor: 'middle' });

    return {
      horizontal,
      width,
      height,
      plot: { x: left, y: top, w: plotW, h: plotH },
      ticks,
      showAxis: !capLabels,
      zero: y0,
      cats,
      marks,
      titles,
    };
  }

  /* ---- horizontal */
  const barT = single ? 16 : k === 2 ? 12 : 10;
  const groupT = k * barT + (k - 1) * GAP;
  const head = chart.xTitle || chart.yTitle ? 24 : 4;
  const tipLabels = single;
  const labelCol = Math.ceil(Math.min(maxCatW, width * 0.36, 220));
  const left = labelCol + 14;
  const tipW = tipLabels ? Math.max(...chart.values[vis[0]].map((v) => (v === null ? 0 : measureText(valueText(v), fTick)))) : 0;
  const axisH = tipLabels ? 4 : 24;
  const target = Math.max(80, height - head - axisH);
  const bandH = clamp(target / n, groupT + 8, groupT + 26);
  const plotH = bandH * n;
  const totalH = Math.ceil(head + plotH + axisH);

  let ticks: AxisTick[] = [];
  let dMin = lo;
  let dMax = hi;
  let right = tipLabels ? Math.ceil(tipW) + 10 : 12;
  let negPad = 0;
  if (tipLabels && lo < 0) {
    negPad = Math.ceil(Math.max(...chart.values[vis[0]].map((v) => (v !== null && v < 0 ? measureText(valueText(v), fTick) : 0)))) + 8;
  }
  if (!tipLabels) {
    const t = niceTicks(lo, hi, clamp(Math.round((width - left) / 90), 2, 7));
    dMin = t.min;
    dMax = t.max;
    const maxAbs = Math.max(Math.abs(t.min), Math.abs(t.max));
    const texts = t.ticks.map((v) => formatTick(v, t.step, chart.unit, maxAbs));
    right = Math.ceil(measureText(texts[texts.length - 1], fTick) / 2) + 4;
    const xs = linearScale(t.min, t.max, left, width - right);
    ticks = t.ticks.map((v, i) => ({ pos: xs(v), text: texts[i], zero: v === 0 }));
  }
  if (dMin === dMax) dMax = dMin + 1;
  const x = linearScale(dMin, dMax, left + negPad, width - right);
  const x0 = x(0);

  chart.categories.forEach((_, c) => {
    vis.forEach((s, j) => {
      const v = chart.values[s][c];
      if (v === null) return;
      const yTop = head + bandH * c + (bandH - groupT) / 2 + j * (barT + GAP);
      const xv = x(v);
      const l = Math.min(xv, x0);
      const w = Math.abs(xv - x0);
      marks.push({
        c,
        s,
        v,
        d: barPath(l, yTop, w, barT, v >= 0 ? 'right' : 'left'),
        anchor: { x: xv, y: yTop + barT / 2 },
        hit: single
          ? { x: 0, y: head + bandH * c, w: width, h: bandH }
          : { x: 0, y: head + bandH * c + (bandH / k) * j, w: width, h: bandH / k },
        label: tipLabels
          ? { x: v >= 0 ? xv + 6 : xv - 6, y: yTop + barT / 2, text: valueText(v), anchor: v >= 0 ? 'start' : 'end' }
          : undefined,
      });
    });
  });

  const cats = chart.categories.map((cat, c) => ({
    x: 0,
    y: head + bandH * (c + 0.5),
    text: fitText(cat, labelCol, fCat),
    anchor: 'start' as const,
  }));
  if (chart.xTitle) titles.push({ x: 0, y: 12, text: fitText(chart.xTitle, labelCol, fTitle), anchor: 'start' });
  if (chart.yTitle) titles.push({ x: left, y: 12, text: fitText(chart.yTitle, width - left, fTitle), anchor: 'start' });

  return {
    horizontal,
    width,
    height: totalH,
    plot: { x: left, y: head, w: width - left - right, h: plotH },
    ticks,
    showAxis: !tipLabels,
    zero: x0,
    cats,
    marks,
    titles,
  };
}

export function BarPlot({ chart, width, height, visible, svgRef, label }: PlotProps) {
  const fontsVersion = useFontsVersion();
  const [active, setActive] = useState<number | null>(null);
  // fontsVersion re-runs the layout once web fonts arrive and text widths change.
  const L = useMemo(() => layoutBars(chart, width, height, visible, fontsVersion), [chart, width, height, visible, fontsVersion]);

  const total = useMemo(
    () => (chart.fromPie ? (chart.values[0] ?? []).reduce<number>((a, v) => a + (v !== null && v > 0 ? v : 0), 0) : 0),
    [chart],
  );

  if (!L) return null;
  const act = active !== null && active < L.marks.length ? L.marks[active] : null;
  const multi = chart.series.length > 1;

  const tip: TipState | null = act
    ? {
        x: act.anchor.x,
        y: act.anchor.y,
        title: chart.categories[act.c],
        rows: [
          {
            key: String(act.s),
            color: chart.series[act.s].color,
            value: formatValue(act.v, chart.unit),
            label: multi ? chart.series[act.s].name : chart.yTitle || chart.series[act.s].name,
            mark: 'rect',
          },
        ],
        note: chart.fromPie && total > 0 ? `${formatPercent(act.v / total)} of total` : undefined,
      }
    : null;

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const next = stepKey(e, L.marks.length, active);
    if (next === undefined) return;
    e.preventDefault();
    setActive(next);
  };

  const live = act ? `${chart.categories[act.c]}, ${multi ? `${chart.series[act.s].name}, ` : ''}${formatValue(act.v, chart.unit)}` : '';
  const { plot } = L;

  return (
    <div className={styles.plot} style={{ height: L.height }}>
      <svg
        ref={svgRef}
        className={styles.svg}
        width={L.width}
        height={L.height}
        viewBox={`0 0 ${L.width} ${L.height}`}
        role="img"
        aria-label={label}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
        onPointerLeave={() => setActive(null)}
      >
        {L.titles.map((t) => (
          <text key={`${t.x}-${t.y}`} className={styles.axisTitle} x={t.x} y={t.y} textAnchor={t.anchor}>
            {t.text}
          </text>
        ))}

        {L.showAxis &&
          L.ticks.map((t) =>
            L.horizontal ? (
              <g key={t.text}>
                {!t.zero && <line className={styles.grid} x1={t.pos} x2={t.pos} y1={plot.y} y2={plot.y + plot.h} />}
                <text className={styles.tick} x={t.pos} y={plot.y + plot.h + 16} textAnchor="middle">
                  {t.text}
                </text>
              </g>
            ) : (
              <g key={t.text}>
                {!t.zero && <line className={styles.grid} x1={plot.x} x2={plot.x + plot.w} y1={t.pos} y2={t.pos} />}
                <text className={styles.tick} x={plot.x - 10} y={t.pos} textAnchor="end" dominantBaseline="central">
                  {t.text}
                </text>
              </g>
            ),
          )}

        <g className={styles.marks} data-active={act ? '' : undefined}>
          {L.marks.map((m, i) => (
            <path key={`${m.c}-${m.s}`} d={m.d} className={styles.bar} data-on={i === active || undefined} style={{ fill: chart.series[m.s].color }} />
          ))}
        </g>

        {L.horizontal ? (
          <line className={styles.baseline} x1={L.zero} x2={L.zero} y1={plot.y} y2={plot.y + plot.h} />
        ) : (
          <line className={styles.baseline} x1={plot.x} x2={plot.x + plot.w} y1={L.zero} y2={L.zero} />
        )}

        {L.marks.map((m, i) =>
          m.label ? (
            <text
              key={`l-${m.c}-${m.s}`}
              className={styles.valueLabel}
              data-on={i === active || undefined}
              x={m.label.x}
              y={m.label.y}
              textAnchor={m.label.anchor}
              dominantBaseline={L.horizontal ? 'central' : undefined}
            >
              {m.label.text}
            </text>
          ) : null,
        )}

        {L.cats.map((c, i) => (
          <text
            key={`c-${i}`}
            className={styles.cat}
            data-on={act?.c === i || undefined}
            x={c.x}
            y={c.y}
            textAnchor={c.anchor}
            dominantBaseline={L.horizontal ? 'central' : undefined}
          >
            {c.text}
          </text>
        ))}

        <g data-export="skip">
          {L.marks.map((m, i) => (
            <rect
              key={`h-${m.c}-${m.s}`}
              className={styles.hit}
              x={m.hit.x}
              y={m.hit.y}
              width={Math.max(0, m.hit.w)}
              height={Math.max(0, m.hit.h)}
              onPointerEnter={() => setActive(i)}
              onPointerDown={() => setActive(i)}
            />
          ))}
        </g>
      </svg>
      <ChartTooltip tip={tip} bounds={{ width: L.width, height: L.height }} />
      <LiveRegion text={live} />
    </div>
  );
}
