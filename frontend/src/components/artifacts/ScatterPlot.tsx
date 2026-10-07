import { useMemo, useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import styles from './ChartFigure.module.css';
import { ChartTooltip, LiveRegion } from './ChartParts';
import type { TipState } from './ChartParts';
import { formatValue } from './format';
import { useFontsVersion } from './hooks';
import type { NormChart } from './normalize';
import { stepKey } from './plotTypes';
import type { PlotProps } from './plotTypes';
import { layoutXY, xLabel } from './xyLayout';
import type { XYLayout } from './xyLayout';

/** Pointer must be within this many px of a dot's centre (hit target >= 24px). */
const HIT_RADIUS = 18;

interface Dot {
  s: number;
  i: number;
  px: number;
  py: number;
  x: number;
  y: number;
  label?: string;
}

function layoutScatter(
  chart: NormChart,
  width: number,
  height: number,
  visible: boolean[],
  _fontsVersion: number,
): { axes: XYLayout; dots: Dot[] } | null {
  const vis = chart.series.map((_, i) => i).filter((i) => visible[i] && (chart.points[i]?.length ?? 0) > 0);
  if (!vis.length) return null;
  const axes = layoutXY(chart, width, height, vis, 'scatter', () => 14);
  if (!axes) return null;
  const dots = vis
    .flatMap((s) => chart.points[s].map((p, i) => ({ s, i, px: axes.x(p.x), py: axes.y(p.y), x: p.x, y: p.y, label: p.label })))
    .sort((a, b) => a.x - b.x || a.y - b.y);
  return { axes, dots };
}

export function ScatterPlot({ chart, width, height, visible, svgRef, label }: PlotProps) {
  const fontsVersion = useFontsVersion();
  const [active, setActive] = useState<number | null>(null);
  const L = useMemo(() => layoutScatter(chart, width, height, visible, fontsVersion), [chart, width, height, visible, fontsVersion]);

  if (!L) return null;
  const { axes, dots } = L;
  const { plot } = axes;
  const act = active !== null && active < dots.length ? dots[active] : null;
  const multi = chart.series.length > 1;

  const xName = chart.xTitle || 'x';
  const yName = chart.yTitle || (multi ? 'y' : chart.series[0]?.name || 'y');
  const tip: TipState | null = act
    ? {
        x: act.px,
        y: act.py,
        title: act.label ?? (multi ? chart.series[act.s].name : ''),
        rows: [
          { key: 'y', color: chart.series[act.s].color, value: formatValue(act.y, chart.unit), label: yName, mark: 'dot' },
          ...(chart.xKind === 'category'
            ? []
            : [{ key: 'x', color: 'var(--text-3)', value: xLabel(chart, act.x), label: xName, mark: 'dot' as const, muted: true }]),
        ],
        note: act.label && multi ? chart.series[act.s].name : undefined,
      }
    : null;

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    let best = -1;
    let bestD = HIT_RADIUS * HIT_RADIUS;
    dots.forEach((d, i) => {
      const dd = (d.px - px) ** 2 + (d.py - py) ** 2;
      if (dd <= bestD) {
        bestD = dd;
        best = i;
      }
    });
    setActive(best >= 0 ? best : null);
  };

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const next = stepKey(e, dots.length, active);
    if (next === undefined) return;
    e.preventDefault();
    setActive(next);
  };

  const live = act ? `${act.label ? `${act.label}, ` : ''}${xName} ${xLabel(chart, act.x)}, ${yName} ${formatValue(act.y, chart.unit)}` : '';

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
            <line className={t.zero ? styles.baseline : styles.grid} x1={plot.x} x2={plot.x + plot.w} y1={t.pos} y2={t.pos} />
            <text className={styles.tick} x={plot.x - 10} y={t.pos} textAnchor="end" dominantBaseline="central">
              {t.text}
            </text>
          </g>
        ))}
        {!axes.zeroInDomain && <line className={styles.baseline} x1={plot.x} x2={plot.x + plot.w} y1={axes.baseY} y2={axes.baseY} />}
        {axes.xTicks.map((t) => (
          <text key={`x-${t.text}-${t.pos}`} className={chart.xKind === 'category' ? styles.cat : styles.tick} x={t.pos} y={plot.y + plot.h + 17} textAnchor="middle">
            {t.text}
          </text>
        ))}

        <g className={styles.marks} data-active={act ? '' : undefined}>
          {dots.map((d, i) => (
            <circle
              key={`${d.s}-${d.i}`}
              className={styles.dot}
              data-on={i === active || undefined}
              cx={d.px}
              cy={d.py}
              r={5}
              style={{ fill: chart.series[d.s].color }}
            />
          ))}
        </g>

        <g data-export="skip">
          {act && <circle className={styles.focusRing} cx={act.px} cy={act.py} r={8.5} />}
          <rect
            className={styles.hit}
            x={plot.x - HIT_RADIUS}
            y={plot.y - HIT_RADIUS}
            width={plot.w + HIT_RADIUS * 2}
            height={plot.h + HIT_RADIUS * 2}
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
