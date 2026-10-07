import { useMemo, useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import styles from './ChartFigure.module.css';
import { ChartTooltip, LiveRegion } from './ChartParts';
import type { TipState } from './ChartParts';
import { formatValue } from './format';
import { polyline, spreadLabels } from './geometry';
import type { Scale } from './geometry';
import { fitText, font, measureText, useFontsVersion } from './hooks';
import type { NormChart } from './normalize';
import { stepKey } from './plotTypes';
import type { PlotProps } from './plotTypes';
import { layoutXY, xLabel } from './xyLayout';
import type { XYLayout } from './xyLayout';

const END_GAP = 15;

interface EndLabel {
  s: number;
  text: string;
  from: { x: number; y: number };
  y: number;
  leader: boolean;
}

interface LineLayout {
  axes: XYLayout;
  xs: number[];
  paths: Array<{ s: number; d: string; area?: string }>;
  ends: Array<{ s: number; x: number; y: number }>;
  labels: EndLabel[];
  labelX: number;
  labelKind: 'name' | 'value' | 'none';
}

function layoutLine(chart: NormChart, width: number, height: number, visible: boolean[], _fontsVersion: number): LineLayout | null {
  const vis = chart.series.map((_, i) => i).filter((i) => visible[i] && (chart.points[i]?.length ?? 0) > 0);
  if (!vis.length) return null;
  const fName = font('ui', 12);
  const fVal = font('mono', 11);
  const single = vis.length === 1;
  let labelKind: LineLayout['labelKind'] = single ? 'value' : vis.length <= 4 && width >= 440 ? 'name' : 'none';
  const last = (s: number) => chart.points[s][chart.points[s].length - 1];
  const texts = new Map<number, string>();
  vis.forEach((s) =>
    texts.set(s, labelKind === 'value' ? formatValue(last(s).y, chart.unit) : fitText(chart.series[s].name, 128, fName)),
  );

  let placed: number[] = [];
  const rightPadFor = (y: Scale, top: number, bottom: number) => {
    if (labelKind === 'none') return 10;
    const targets = vis.map((s) => y(last(s).y));
    placed = spreadLabels(targets, END_GAP, top + 6, bottom - 6);
    if (placed.some((p, i) => Math.abs(p - targets[i]) > 26)) {
      labelKind = 'none';
      return 10;
    }
    const f = labelKind === 'value' ? fVal : fName;
    return Math.ceil(Math.max(...vis.map((s) => measureText(texts.get(s) ?? '', f)))) + 18;
  };

  const axes = layoutXY(chart, width, height, vis, 'line', rightPadFor);
  if (!axes) return null;
  const { x, y } = axes;

  const xs = [...new Set(vis.flatMap((s) => chart.points[s].map((p) => p.x)))].sort((a, b) => a - b);
  const paths = vis.map((s) => {
    const pts = chart.points[s].map((p) => ({ x: x(p.x), y: y(p.y) }));
    const gapAt = (i: number) => chart.xKind === 'category' && chart.points[s][i].x - chart.points[s][i - 1].x > 1;
    const d = polyline(pts, gapAt);
    const hasGap = chart.points[s].some((_, i) => i > 0 && gapAt(i));
    const area =
      single && axes.zeroInDomain && pts.length > 1 && !hasGap
        ? `${d}L${pts[pts.length - 1].x},${axes.baseY}L${pts[0].x},${axes.baseY}Z`
        : undefined;
    return { s, d, area };
  });
  const ends = vis.map((s) => ({ s, x: x(last(s).x), y: y(last(s).y) }));
  const labelX = axes.plot.x + axes.plot.w + 10;
  const labels: EndLabel[] =
    labelKind === 'none'
      ? []
      : vis.map((s, i) => {
          const from = ends[i];
          const ly = placed[i] ?? from.y;
          return { s, text: texts.get(s) ?? '', from, y: ly, leader: Math.abs(ly - from.y) > 2 || from.x < axes.plot.x + axes.plot.w - 1 };
        });

  return { axes, xs, paths, ends, labels, labelX, labelKind };
}

export function LinePlot({ chart, width, height, visible, svgRef, label }: PlotProps) {
  const fontsVersion = useFontsVersion();
  const [active, setActive] = useState<number | null>(null);
  const L = useMemo(() => layoutLine(chart, width, height, visible, fontsVersion), [chart, width, height, visible, fontsVersion]);

  if (!L) return null;
  const { axes } = L;
  const { plot } = axes;
  const vis = L.paths.map((p) => p.s);
  const ax = active !== null && active < L.xs.length ? L.xs[active] : null;
  const crossX = ax !== null ? axes.x(ax) : null;
  const dots =
    ax === null
      ? []
      : vis
          .map((s) => {
            const p = chart.points[s].find((q) => q.x === ax);
            return p ? { s, x: axes.x(p.x), y: axes.y(p.y), v: p.y } : null;
          })
          .filter((d): d is { s: number; x: number; y: number; v: number } => d !== null);

  const multi = chart.series.length > 1;
  const tip: TipState | null =
    ax !== null && crossX !== null
      ? {
          x: crossX,
          y: dots.length ? Math.min(...dots.map((d) => d.y)) : plot.y + plot.h / 2,
          title: xLabel(chart, ax),
          rows: vis.map((s) => {
            const d = dots.find((q) => q.s === s);
            return {
              key: String(s),
              color: chart.series[s].color,
              value: d ? formatValue(d.v, chart.unit) : '—',
              label: multi ? chart.series[s].name : chart.yTitle || chart.series[s].name,
              mark: 'line' as const,
              muted: !d,
            };
          }),
        }
      : null;

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || !L.xs.length) return;
    const px = e.clientX - rect.left;
    let best = 0;
    let bestD = Infinity;
    L.xs.forEach((v, i) => {
      const d = Math.abs(axes.x(v) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setActive(best);
  };

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const next = stepKey(e, L.xs.length, active);
    if (next === undefined) return;
    e.preventDefault();
    setActive(next);
  };

  const live =
    ax !== null ? `${xLabel(chart, ax)}: ${dots.map((d) => `${multi ? `${chart.series[d.s].name} ` : ''}${formatValue(d.v, chart.unit)}`).join(', ')}` : '';

  return (
    <div className={styles.plot} style={{ height: axes.height }}>
      <svg
        ref={svgRef}
        className={styles.svg}
        width={axes.width}
        height={axes.height}
        viewBox={`0 0 ${axes.width} ${axes.height}`}
        role="img"
        aria-label={label}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
      >
        {axes.titles.map((t) => (
          <text key={`${t.x}-${t.y}`} className={styles.axisTitle} x={t.x} y={t.y} textAnchor={t.anchor}>
            {t.text}
          </text>
        ))}
        {axes.yTicks.map((t) => (
          <g key={t.text}>
            {!t.zero && <line className={styles.grid} x1={plot.x} x2={plot.x + plot.w} y1={t.pos} y2={t.pos} />}
            <text className={styles.tick} x={plot.x - 10} y={t.pos} textAnchor="end" dominantBaseline="central">
              {t.text}
            </text>
          </g>
        ))}
        <line className={styles.baseline} x1={plot.x} x2={plot.x + plot.w} y1={axes.baseY} y2={axes.baseY} />
        {axes.xTicks.map((t) => (
          <text key={`x-${t.text}-${t.pos}`} className={chart.xKind === 'category' ? styles.cat : styles.tick} x={t.pos} y={plot.y + plot.h + 17} textAnchor="middle">
            {t.text}
          </text>
        ))}

        {crossX !== null && <line data-export="skip" className={styles.crosshair} x1={crossX} x2={crossX} y1={plot.y} y2={plot.y + plot.h} />}

        {L.paths.map((p) =>
          p.area ? <path key={`a-${p.s}`} d={p.area} className={styles.area} style={{ fill: chart.series[p.s].color }} /> : null,
        )}
        {L.paths.map((p) => (
          <path key={`l-${p.s}`} d={p.d} className={styles.line} style={{ stroke: chart.series[p.s].color }} />
        ))}
        {L.ends.map((e) => (
          <circle key={`e-${e.s}`} className={styles.dot} cx={e.x} cy={e.y} r={5} style={{ fill: chart.series[e.s].color }} />
        ))}

        {L.labels.map((l) => (
          <g key={`n-${l.s}`}>
            {l.leader && <line className={styles.leader} x1={l.from.x + 7} y1={l.from.y} x2={L.labelX - 4} y2={l.y} />}
            <text
              className={L.labelKind === 'value' ? styles.valueLabel : styles.endLabel}
              x={L.labelX}
              y={l.y}
              dominantBaseline="central"
            >
              {l.text}
            </text>
          </g>
        ))}

        <g data-export="skip">
          {dots.map((d) => (
            <circle key={`d-${d.s}`} className={styles.dot} cx={d.x} cy={d.y} r={5} style={{ fill: chart.series[d.s].color }} />
          ))}
          <rect
            className={styles.hit}
            x={plot.x}
            y={plot.y}
            width={plot.w}
            height={plot.h}
            onPointerMove={onMove}
            onPointerDown={onMove}
            onPointerLeave={() => setActive(null)}
          />
        </g>
      </svg>
      <ChartTooltip tip={tip} bounds={{ width: axes.width, height: axes.height }} />
      <LiveRegion text={live} />
    </div>
  );
}
