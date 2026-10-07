import { useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ChartColumn, ChartNoAxesColumn, Download, ImageDown, Maximize2, Table2 } from 'lucide-react';
import type { ChartArtifact } from '../../api';
import styles from './ChartFigure.module.css';
import { BarPlot } from './BarPlot';
import { DonutPlot } from './DonutPlot';
import { LinePlot } from './LinePlot';
import { ScatterPlot } from './ScatterPlot';
import { chartSvgString, downloadBlob, slugify, tableToCsv } from './exporters';
import type { SvgLegendItem } from './exporters';
import { formatPrecise } from './format';
import { useElementSize } from './hooks';
import { formLabel, normalizeChart, slotColor } from './normalize';
import type { NormChart } from './normalize';
import type { PlotProps } from './plotTypes';

export interface ChartFigureProps {
  chart: ChartArtifact;
  /** inline: card inside an answer (~240px plot). full: fills its container (artifact panel). */
  variant?: 'inline' | 'full';
  onCite?: (n: number) => void;
  /** Inline only: opens the chart in the side panel. */
  onExpand?: () => void;
}

const NO_HIDDEN: number[] = [];
const ICON = { size: 16, strokeWidth: 1.75 } as const;

function metaLine(n: NormChart): string {
  const parts: string[] = [];
  const plural = (k: number, word: string) => `${k} ${word}${k === 1 ? '' : 's'}`;
  if (n.fromPie) {
    parts.push('Pie data', `${plural(n.categories.length, 'slice')}, shown as ranked bars`);
  } else if (n.form === 'donut') {
    parts.push('Donut chart', plural(n.categories.length, 'slice'));
  } else if (n.form === 'bar') {
    parts.push(formLabel(n), plural(n.categories.length, 'category').replace('categorys', 'categories'));
  } else {
    const count = n.table.rows.length;
    parts.push(formLabel(n), plural(n.form === 'scatter' ? count : n.points.reduce((m, p) => Math.max(m, p.length), 0), 'point'));
  }
  const original = n.table.columns.length - n.table.numericFrom;
  if (n.form !== 'donut' && !n.fromPie && n.form !== 'scatter' && original > 1) parts.push(plural(original, 'series').replace('seriess', 'series'));
  const other = n.series.find((s) => s.other);
  if (other) parts.push(`${other.name.replace(/^Other \((\d+)\)$/, '$1')} folded into Other`);
  return parts.join(' · ');
}

function ToolButton({ label, onClick, disabled, pressed, children }: { label: string; onClick: () => void; disabled?: boolean; pressed?: boolean; children: ReactNode }) {
  return (
    <button type="button" className={styles.tool} aria-label={label} title={label} onClick={onClick} disabled={disabled} aria-pressed={pressed}>
      {children}
    </button>
  );
}

function ChartTable({ chart, full }: { chart: NormChart; full: boolean }) {
  const { columns, rows, numericFrom } = chart.table;
  const scatter = chart.form === 'scatter' && chart.xKind !== 'category';
  return (
    <div className={styles.tableWrap} data-full={full || undefined}>
      <table className={styles.table}>
        <caption className="visually-hidden">{chart.title}, data table</caption>
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={`${c}-${i}`} scope="col" className={i >= numericFrom ? styles.num : undefined}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) =>
                ci === 0 ? (
                  <th key={ci} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={ci} className={styles.num}>
                    {typeof cell === 'number' ? formatPrecise(cell, scatter && ci === 1 ? chart.xUnit : chart.unit) : '—'}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * An answer chart: pure SVG, sized to its container, with a hover/keyboard
 * readout, a table twin, CSV (and in the full variant SVG) export, caption
 * and source chips. Accepts any stored chart shape; renders a quiet empty
 * state when nothing is plottable.
 */
export function ChartFigure({ chart, variant = 'inline', onCite, onExpand }: ChartFigureProps) {
  const norm = useMemo(() => normalizeChart(chart), [chart]);
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const [hiddenFor, setHiddenFor] = useState<{ norm: NormChart; hidden: number[] }>({ norm, hidden: NO_HIDDEN });
  const hidden = hiddenFor.norm === norm ? hiddenFor.hidden : NO_HIDDEN;
  const visible = useMemo(() => norm.series.map((_, i) => !hidden.includes(i)), [norm, hidden]);
  const [bodyRef, size] = useElementSize<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const titleId = useId();
  const full = variant === 'full';

  const mark: SvgLegendItem['shape'] = norm.form === 'line' ? 'line' : norm.form === 'scatter' ? 'dot' : 'rect';
  const showLegend = view === 'chart' && !norm.empty && norm.form !== 'donut' && norm.series.length >= 2;

  const toggleSeries = (i: number) => {
    const next = hidden.includes(i) ? hidden.filter((h) => h !== i) : [...hidden, i];
    if (next.length >= norm.series.length) return;
    setHiddenFor({ norm, hidden: next });
  };

  const downloadCsv = () => {
    downloadBlob(`${slugify(norm.title)}.csv`, new Blob([tableToCsv(norm.table)], { type: 'text/csv;charset=utf-8' }));
  };

  const downloadSvg = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const legend: SvgLegendItem[] =
      norm.form === 'donut'
        ? norm.categories.map((c, i) => ({ label: c, color: slotColor(i, 6), shape: 'rect' }))
        : norm.series.length > 1
          ? norm.series.filter((_, i) => visible[i]).map((s) => ({ label: s.name, color: s.color, shape: mark }))
          : [];
    const out = chartSvgString(svg, { title: norm.title, legend, caption: norm.caption });
    downloadBlob(`${slugify(norm.title)}.svg`, new Blob([out], { type: 'image/svg+xml;charset=utf-8' }));
  };

  const plotHeight = full ? Math.max(260, size.height - 4) : 248;
  const plotProps: PlotProps = {
    chart: norm,
    width: size.width,
    height: plotHeight,
    visible,
    svgRef,
    variant,
    label: `${formLabel(norm)}: ${norm.title}. Use arrow keys to read values; the table view lists every value.`,
  };

  let plot: ReactNode = null;
  if (size.width > 0) {
    if (norm.form === 'line') plot = <LinePlot {...plotProps} />;
    else if (norm.form === 'scatter') plot = <ScatterPlot {...plotProps} />;
    else if (norm.form === 'donut') plot = <DonutPlot {...plotProps} />;
    else plot = <BarPlot {...plotProps} />;
  }

  return (
    <figure className={styles.figure} data-variant={variant} aria-labelledby={titleId}>
      <header className={styles.head}>
        <div className={styles.heading}>
          <h3 id={titleId} className={full ? 'visually-hidden' : styles.title}>
            {norm.title}
          </h3>
          {!norm.empty && <p className={styles.meta}>{metaLine(norm)}</p>}
        </div>
        {!norm.empty && (
          <div className={styles.tools} role="toolbar" aria-label="Chart tools">
            <ToolButton
              label={view === 'chart' ? 'Show data table' : 'Show chart'}
              onClick={() => setView(view === 'chart' ? 'table' : 'chart')}
            >
              {view === 'chart' ? <Table2 {...ICON} /> : <ChartColumn {...ICON} />}
            </ToolButton>
            <ToolButton label="Download CSV" onClick={downloadCsv}>
              <Download {...ICON} />
            </ToolButton>
            {full && (
              <ToolButton label="Download SVG" onClick={downloadSvg} disabled={view !== 'chart'}>
                <ImageDown {...ICON} />
              </ToolButton>
            )}
            {!full && onExpand && (
              <ToolButton label="Open in panel" onClick={onExpand}>
                <Maximize2 {...ICON} />
              </ToolButton>
            )}
          </div>
        )}
      </header>

      {showLegend && (
        <ul className={styles.legend} aria-label="Series (select to show or hide)">
          {norm.series.map((s, i) => (
            <li key={`${s.name}-${i}`}>
              <button
                type="button"
                className={styles.legendItem}
                aria-pressed={visible[i]}
                onClick={() => toggleSeries(i)}
                title={visible[i] ? `Hide ${s.name}` : `Show ${s.name}`}
              >
                <span className={styles.swatch} data-shape={mark} style={{ background: s.color }} aria-hidden="true" />
                <span className={styles.legendText}>{s.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div ref={bodyRef} className={styles.body} data-view={view}>
        {norm.empty ? (
          <div className={styles.empty}>
            <ChartNoAxesColumn size={20} strokeWidth={1.75} className={styles.emptyIcon} aria-hidden="true" />
            <p className={styles.emptyTitle}>No plottable data</p>
            <p className={styles.emptyText}>This chart arrived without numeric values to draw.</p>
          </div>
        ) : view === 'table' ? (
          <ChartTable chart={norm} full={full} />
        ) : (
          plot
        )}
      </div>

      {(norm.caption || norm.sourceNs.length > 0) && (
        <figcaption className={styles.caption}>
          {norm.caption && <p>{norm.caption}</p>}
          {norm.sourceNs.length > 0 && (
            <div className={styles.sources}>
              <span className={styles.sourcesLabel}>Sources</span>
              {norm.sourceNs.map((n) =>
                onCite ? (
                  <button key={n} type="button" className={styles.cite} onClick={() => onCite(n)} aria-label={`Show source ${n}`}>
                    {n}
                  </button>
                ) : (
                  <span key={n} className={styles.cite}>
                    {n}
                  </span>
                ),
              )}
            </div>
          )}
        </figcaption>
      )}
    </figure>
  );
}
