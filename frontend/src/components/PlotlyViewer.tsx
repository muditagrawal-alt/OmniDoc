import React from 'react';
import { BarChart3, TrendingUp } from 'lucide-react';

interface PlotlyViewerProps {
  artifact: any;
}

export const PlotlyViewer: React.FC<PlotlyViewerProps> = ({ artifact }) => {
  if (!artifact) return null;

  const spec = artifact.spec || artifact;
  const title = artifact.title || spec?.layout?.title?.text || spec?.layout?.title || 'Analytical Visualization';
  const chartType = artifact.chart_type || (spec?.data && spec.data[0]?.type) || 'bar';

  // Extract series data
  const data = spec?.data || [];
  const primarySeries = data[0] || {};
  const xLabels: any[] = primarySeries.x || [];
  const yValues: any[] = primarySeries.y || [];

  // Compute maximum for SVG scaling
  const numericY = yValues.map(v => typeof v === 'number' ? v : parseFloat(v) || 0);
  const maxY = Math.max(...numericY, 1);

  return (
    <div style={{
      margin: '0.85rem 0',
      backgroundColor: 'rgba(21, 25, 34, 0.7)',
      border: '1px solid var(--border-medium)',
      borderRadius: 'var(--radius-lg)',
      padding: '1rem',
      overflow: 'hidden',
    }}>
      {/* Title */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '1rem',
        borderBottom: '1px solid var(--border-subtle)',
        paddingBottom: '0.5rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-primary)', fontWeight: 600, fontSize: '0.88rem' }}>
          {chartType === 'line' ? <TrendingUp size={16} style={{ color: 'var(--accent-primary)' }} /> : <BarChart3 size={16} style={{ color: 'var(--accent-primary)' }} />}
          <span>{title}</span>
        </div>
        <span style={{
          fontSize: '0.7rem',
          color: 'var(--text-muted)',
          backgroundColor: 'rgba(255, 255, 255, 0.05)',
          padding: '0.15rem 0.45rem',
          borderRadius: 'var(--radius-sm)',
          textTransform: 'uppercase'
        }}>
          {chartType}
        </span>
      </div>

      {/* Responsive Visual SVG Rendering */}
      {xLabels.length > 0 && yValues.length > 0 ? (
        <div style={{ width: '100%', height: '180px', display: 'flex', alignItems: 'flex-end', gap: '1rem', padding: '1rem 0.5rem 0' }}>
          {xLabels.map((label, idx) => {
            const val = numericY[idx] || 0;
            const heightPct = Math.max(12, Math.round((val / maxY) * 100));
            return (
              <div key={idx} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-end' }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '0.25rem', fontFamily: 'var(--font-mono)' }}>
                  {val.toLocaleString()}
                </span>
                <div style={{
                  width: '100%',
                  maxWidth: '48px',
                  height: `${heightPct}%`,
                  background: 'linear-gradient(180deg, #3b82f6 0%, #1d4ed8 100%)',
                  borderRadius: '6px 6px 0 0',
                  boxShadow: '0 2px 8px rgba(59, 130, 246, 0.3)',
                  transition: 'height 0.4s ease-out'
                }} />
                <span style={{
                  fontSize: '0.74rem',
                  color: 'var(--text-secondary)',
                  marginTop: '0.4rem',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: '70px',
                  textAlign: 'center'
                }}>
                  {label}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{
          padding: '1.5rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.8rem',
          fontFamily: 'var(--font-mono)'
        }}>
          Interactive Plotly Specification Loaded
        </div>
      )}
    </div>
  );
};
