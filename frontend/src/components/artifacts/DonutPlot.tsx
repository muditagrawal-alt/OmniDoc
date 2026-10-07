import { useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import styles from './ChartFigure.module.css';
import { ChartTooltip, LiveRegion } from './ChartParts';
import type { TipState } from './ChartParts';
import { formatPercent, formatValue } from './format';
import { arcPath } from './geometry';
import { slotColor } from './normalize';
import { stepKey } from './plotTypes';
import type { PlotProps } from './plotTypes';

/** Part-to-whole at a glance, only ever used for 3-6 positive slices. */
export function DonutPlot({ chart, width, height, svgRef, label, variant }: PlotProps) {
  const [active, setActive] = useState<number | null>(null);
  const side = width >= 460;

  const model = useMemo(() => {
    const values = (chart.values[0] ?? []).map((v) => (v !== null && v > 0 ? v : 0));
    const total = values.reduce((a, b) => a + b, 0);
    const full = variant === 'full';
    const cap = full ? 320 : 216;
    const D = Math.max(120, Math.floor(side ? Math.min(height - 16, cap, width * (full ? 0.5 : 0.42)) : Math.min(width - 32, cap)));
    const R = D / 2;
    const r0 = R - Math.max(18, R * 0.3);
    const pad = 8;
    const cx = R + pad;
    const cy = R + pad;
    const rm = (r0 + R) / 2;
    const slices = [];
    for (let i = 0, a0 = 0; i < values.length; i++) {
      const v = values[i];
      const a1 = a0 + (total > 0 ? (v / total) * Math.PI * 2 : 0);
      const mid = (a0 + a1) / 2;
      slices.push({
        i,
        v,
        share: total > 0 ? v / total : 0,
        d: arcPath(cx, cy, r0, R, a0, a1),
        hit: arcPath(cx, cy, Math.max(0, r0 - 6), R + 6, a0, a1),
        anchor: { x: cx + rm * Math.sin(mid), y: cy - rm * Math.cos(mid) },
        color: slotColor(i, 6),
      });
      a0 = a1;
    }
    return { total, slices, size: D + pad * 2, cx, cy, r0 };
  }, [chart, width, height, side, variant]);

  const act = active !== null ? model.slices[active] : null;
  const tip: TipState | null = act
    ? {
        x: act.anchor.x,
        y: act.anchor.y,
        title: chart.categories[act.i],
        rows: [{ key: 'v', color: act.color, value: formatValue(act.v, chart.unit), label: chart.yTitle || chart.series[0]?.name || 'Value', mark: 'rect' }],
        note: `${formatPercent(act.share)} of total`,
      }
    : null;

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const next = stepKey(e, model.slices.length, active);
    if (next === undefined) return;
    e.preventDefault();
    setActive(next);
  };

  const live = act ? `${chart.categories[act.i]}, ${formatValue(act.v, chart.unit)}, ${formatPercent(act.share)} of total` : '';

  return (
    <div className={styles.donutWrap} data-side={side || undefined}>
      <div className={styles.plot} style={{ height: model.size, width: model.size }}>
        <svg
          ref={svgRef}
          className={styles.svg}
          width={model.size}
          height={model.size}
          viewBox={`0 0 ${model.size} ${model.size}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onBlur={() => setActive(null)}
          onPointerLeave={() => setActive(null)}
        >
          <g className={styles.marks} data-active={act ? '' : undefined}>
            {model.slices.map((s) => (
              <path key={s.i} d={s.d} className={styles.slice} data-on={s.i === active || undefined} style={{ fill: s.color }} />
            ))}
          </g>
          <text className={styles.centerLabel} x={model.cx} y={model.cy - 10} textAnchor="middle" dominantBaseline="central">
            Total
          </text>
          <text className={styles.centerValue} x={model.cx} y={model.cy + 10} textAnchor="middle" dominantBaseline="central">
            {formatValue(model.total, chart.unit)}
          </text>
          <g data-export="skip">
            {model.slices.map((s) => (
              <path key={s.i} d={s.hit} className={styles.hit} onPointerEnter={() => setActive(s.i)} onPointerDown={() => setActive(s.i)} />
            ))}
          </g>
        </svg>
        <ChartTooltip tip={tip} bounds={{ width: model.size, height: model.size }} />
      </div>

      <ul className={styles.donutLegend} aria-label="Slices">
        {model.slices.map((s) => (
          <li
            key={s.i}
            className={styles.donutRow}
            data-on={s.i === active || undefined}
            data-dim={(active !== null && s.i !== active) || undefined}
            onPointerEnter={() => setActive(s.i)}
            onPointerLeave={() => setActive(null)}
          >
            <span className={styles.swatch} data-shape="rect" style={{ background: s.color }} aria-hidden="true" />
            <span className={styles.donutName}>{chart.categories[s.i]}</span>
            <span className={styles.donutValue}>{formatValue(s.v, chart.unit)}</span>
            <span className={styles.donutShare}>{formatPercent(s.share)}</span>
          </li>
        ))}
      </ul>
      <LiveRegion text={live} />
    </div>
  );
}
