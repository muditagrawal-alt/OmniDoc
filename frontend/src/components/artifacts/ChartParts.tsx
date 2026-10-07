import { useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import styles from './ChartFigure.module.css';

export interface TipRow {
  key: string;
  color: string;
  value: string;
  label: string;
  mark?: 'line' | 'rect' | 'dot';
  muted?: boolean;
}

export interface TipState {
  /** Anchor in plot-local pixels. */
  x: number;
  y: number;
  title: string;
  rows: TipRow[];
  note?: string;
}

/**
 * Hover/focus readout. Values lead (strong, mono), series names follow;
 * each row is keyed by a short stroke of the series colour. Positioned next
 * to its anchor and kept inside the plot.
 */
export function ChartTooltip({ tip, bounds }: { tip: TipState | null; bounds: { width: number; height: number } }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!tip || !el) {
      setPos(null);
      return;
    }
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const gap = 14;
    let left = tip.x + gap;
    if (left + w > bounds.width - 2) left = tip.x - gap - w;
    if (left < 2) left = Math.max(2, Math.min(bounds.width - w - 2, tip.x - w / 2));
    let top = tip.y - h / 2;
    top = Math.max(2, Math.min(bounds.height - h - 2, top));
    setPos({ left, top });
  }, [tip, bounds.width, bounds.height]);

  if (!tip) return null;
  const style: CSSProperties = pos ? { transform: `translate(${pos.left}px, ${pos.top}px)` } : { visibility: 'hidden' };
  return (
    <div ref={ref} className={styles.tooltip} style={style} aria-hidden="true">
      {tip.title && <div className={styles.tipTitle}>{tip.title}</div>}
      <div className={styles.tipRows}>
        {tip.rows.map((r) => (
          <div key={r.key} className={styles.tipRow} data-muted={r.muted || undefined}>
            <span className={styles.tipKey} data-mark={r.mark ?? 'line'} style={{ background: r.color }} />
            <span className={styles.tipValue}>{r.value}</span>
            <span className={styles.tipLabel}>{r.label}</span>
          </div>
        ))}
      </div>
      {tip.note && <div className={styles.tipNote}>{tip.note}</div>}
    </div>
  );
}

/** Announces the keyboard-focused value to screen readers. */
export function LiveRegion({ text }: { text: string }) {
  return (
    <div className="visually-hidden" aria-live="polite" aria-atomic="true">
      {text}
    </div>
  );
}

/** Plot container: positions the tooltip layer over the SVG. */
export function PlotFrame({ height, children }: { height: number; children: ReactNode }) {
  return (
    <div className={styles.plot} style={{ height }}>
      {children}
    </div>
  );
}
