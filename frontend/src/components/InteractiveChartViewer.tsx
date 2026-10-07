import React, { useState } from 'react';
import { BarChart3, TrendingUp, Table, CheckCircle2 } from 'lucide-react';

interface InteractiveChartViewerProps {
  artifact: any;
}

export const InteractiveChartViewer: React.FC<InteractiveChartViewerProps> = ({ artifact }) => {
  if (!artifact) return null;

  const [viewMode, setViewMode] = useState<'bar' | 'line' | 'table'>('bar');
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const title = artifact.title || 'Data Analytics & Trend Analysis';
  const caption = artifact.caption || '';
  const spec = artifact.plotly_spec || {};
  const dataSeries = (spec.data && spec.data[0]) || {};

  // Extract raw or parsed points
  const rawX: any[] = dataSeries.x || (artifact.underlying_data && artifact.underlying_data.map((d: any) => d.x || d.label || d.year)) || [];
  const rawY: any[] = dataSeries.y || (artifact.underlying_data && artifact.underlying_data.map((d: any) => d.y || d.value)) || [];

  const points = rawX.map((xVal, i) => {
    const num = typeof rawY[i] === 'number' ? rawY[i] : parseFloat(rawY[i]) || 0;
    const detail = (artifact.underlying_data && artifact.underlying_data[i]?.detail) || '';
    return {
      label: String(xVal),
      value: num,
      detail: detail
    };
  });

  if (points.length === 0) return null;

  const maxVal = Math.max(...points.map(p => p.value), 1);

  return (
    <div style={{
      margin: '1rem 0',
      backgroundColor: '#0b0f19',
      border: '1px solid rgba(59, 130, 246, 0.25)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.45)'
    }}>
      {/* Top Header & View Mode Switcher */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.65rem 1rem',
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BarChart3 size={15} style={{ color: 'var(--accent-primary)' }} />
          <span style={{ fontSize: '0.85rem', fontWeight: 650, color: 'var(--text-primary)' }}>
            {title}
          </span>
        </div>

        {/* View Mode Switcher Buttons */}
        <div style={{
          display: 'flex',
          backgroundColor: 'rgba(255, 255, 255, 0.04)',
          borderRadius: 'var(--radius-sm)',
          padding: '2px',
          border: '1px solid rgba(255, 255, 255, 0.06)'
        }}>
          <button
            onClick={() => setViewMode('bar')}
            title="Bar Chart Mode"
            style={{
              padding: '0.2rem 0.5rem',
              fontSize: '0.72rem',
              borderRadius: '4px',
              border: 'none',
              backgroundColor: viewMode === 'bar' ? 'var(--accent-primary)' : 'transparent',
              color: viewMode === 'bar' ? '#ffffff' : 'var(--text-dim)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem'
            }}
          >
            <BarChart3 size={11} />
            <span>Bar</span>
          </button>

          <button
            onClick={() => setViewMode('line')}
            title="Area & Trendline Mode"
            style={{
              padding: '0.2rem 0.5rem',
              fontSize: '0.72rem',
              borderRadius: '4px',
              border: 'none',
              backgroundColor: viewMode === 'line' ? 'var(--accent-primary)' : 'transparent',
              color: viewMode === 'line' ? '#ffffff' : 'var(--text-dim)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem'
            }}
          >
            <TrendingUp size={11} />
            <span>Trend</span>
          </button>

          <button
            onClick={() => setViewMode('table')}
            title="Table Data Mode"
            style={{
              padding: '0.2rem 0.5rem',
              fontSize: '0.72rem',
              borderRadius: '4px',
              border: 'none',
              backgroundColor: viewMode === 'table' ? 'var(--accent-primary)' : 'transparent',
              color: viewMode === 'table' ? '#ffffff' : 'var(--text-dim)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem'
            }}
          >
            <Table size={11} />
            <span>Data</span>
          </button>
        </div>
      </div>

      {/* Main Chart Body */}
      <div style={{ padding: '1.25rem 1rem 1rem 1rem', minHeight: '220px' }}>
        {viewMode === 'bar' && (
          <div style={{
            position: 'relative',
            height: '190px',
            display: 'flex',
            alignItems: 'flex-end',
            gap: '1.25rem',
            padding: '0 0.5rem',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)'
          }}>
            {/* Background Grid Lines */}
            <div style={{ position: 'absolute', top: '25%', left: 0, right: 0, borderTop: '1px dashed rgba(255,255,255,0.04)' }} />
            <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, borderTop: '1px dashed rgba(255,255,255,0.04)' }} />
            <div style={{ position: 'absolute', top: '75%', left: 0, right: 0, borderTop: '1px dashed rgba(255,255,255,0.04)' }} />

            {points.map((pt, idx) => {
              const heightPct = Math.max(14, Math.round((pt.value / maxVal) * 100));
              const isHovered = hoveredIdx === idx;

              return (
                <div
                  key={idx}
                  onMouseEnter={() => setHoveredIdx(idx)}
                  onMouseLeave={() => setHoveredIdx(null)}
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    height: '100%',
                    justifyContent: 'flex-end',
                    cursor: 'pointer',
                    position: 'relative'
                  }}
                >
                  {/* Floating Tooltip Card */}
                  {isHovered && (
                    <div style={{
                      position: 'absolute',
                      bottom: `${heightPct + 12}%`,
                      zIndex: 10,
                      backgroundColor: 'rgba(15, 23, 42, 0.95)',
                      backdropFilter: 'blur(8px)',
                      border: '1px solid rgba(59, 130, 246, 0.4)',
                      borderRadius: '6px',
                      padding: '0.4rem 0.65rem',
                      whiteSpace: 'nowrap',
                      boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5)',
                      pointerEvents: 'none',
                      animation: 'fadeIn 0.15s ease-out'
                    }}>
                      <div style={{ fontSize: '0.72rem', color: '#93c5fd', fontWeight: 600 }}>{pt.label}</div>
                      <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#ffffff', fontFamily: 'var(--font-mono)' }}>
                        {pt.value.toLocaleString()}
                      </div>
                      {pt.detail && (
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: '2px' }}>{pt.detail}</div>
                      )}
                    </div>
                  )}

                  {/* Value on top of bar */}
                  <span style={{
                    fontSize: '0.72rem',
                    color: isHovered ? '#60a5fa' : 'var(--text-dim)',
                    fontFamily: 'var(--font-mono)',
                    marginBottom: '0.35rem',
                    transition: 'color 0.2s ease'
                  }}>
                    {pt.value > 1000 ? `${(pt.value / 1000).toFixed(1)}k` : pt.value}
                  </span>

                  {/* Bar pillar */}
                  <div style={{
                    width: '100%',
                    maxWidth: '46px',
                    height: `${heightPct}%`,
                    background: isHovered
                      ? 'linear-gradient(180deg, #60a5fa 0%, #2563eb 100%)'
                      : 'linear-gradient(180deg, #3b82f6 0%, #1d4ed8 100%)',
                    borderRadius: '6px 6px 0 0',
                    boxShadow: isHovered ? '0 0 16px rgba(59, 130, 246, 0.65)' : '0 2px 8px rgba(59, 130, 246, 0.25)',
                    transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
                  }} />

                  {/* Label under bar */}
                  <span style={{
                    fontSize: '0.72rem',
                    color: isHovered ? 'var(--text-primary)' : 'var(--text-secondary)',
                    marginTop: '0.45rem',
                    textAlign: 'center',
                    maxWidth: '80px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }}>
                    {pt.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {viewMode === 'line' && (
          <div style={{ position: 'relative', height: '190px', width: '100%' }}>
            {/* SVG Interactive Area Trendline with compliant viewBox and coordinates */}
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              <defs>
                <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.45" />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Area path */}
              {(() => {
                const step = points.length > 1 ? 100 / (points.length - 1) : 50;
                const pathCoords = points.map((p, idx) => {
                  const x = (idx * step).toFixed(2);
                  const yVal = Math.max(0, Math.min(maxVal, p.value));
                  const y = (85 - (yVal / Math.max(1, maxVal)) * 70).toFixed(2);
                  return `${x} ${y}`;
                });
                const d = `M 0 85 L ${pathCoords.join(' L ')} L 100 85 Z`;
                return <path d={d} fill="url(#areaGradient)" />;
              })()}

              {/* Line stroke */}
              {(() => {
                const step = points.length > 1 ? 100 / (points.length - 1) : 50;
                const pathCoords = points.map((p, idx) => {
                  const x = (idx * step).toFixed(2);
                  const yVal = Math.max(0, Math.min(maxVal, p.value));
                  const y = (85 - (yVal / Math.max(1, maxVal)) * 70).toFixed(2);
                  return `${x} ${y}`;
                });
                const d = `M ${pathCoords.join(' L ')}`;
                return (
                  <path
                    d={d}
                    fill="none"
                    stroke="#3b82f6"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })()}

              {/* Interactive Point circles */}
              {points.map((p, idx) => {
                const step = points.length > 1 ? 100 / (points.length - 1) : 50;
                const cx = Number((idx * step).toFixed(2));
                const yVal = Math.max(0, Math.min(maxVal, p.value));
                const cy = Number((85 - (yVal / Math.max(1, maxVal)) * 70).toFixed(2));
                const isHovered = hoveredIdx === idx;

                return (
                  <g key={idx} onMouseEnter={() => setHoveredIdx(idx)} onMouseLeave={() => setHoveredIdx(null)}>
                    <circle
                      cx={cx}
                      cy={cy}
                      r={isHovered ? 2.5 : 1.8}
                      fill={isHovered ? '#60a5fa' : '#3b82f6'}
                      stroke="#ffffff"
                      strokeWidth={0.8}
                      vectorEffect="non-scaling-stroke"
                      style={{ cursor: 'pointer', transition: 'all 0.2s ease' }}
                    />
                  </g>
                );
              })}
            </svg>

            {/* Labels below trendline */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '0.5rem',
              borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              paddingTop: '0.4rem'
            }}>
              {points.map((p, idx) => (
                <span key={idx} style={{
                  fontSize: '0.72rem',
                  color: hoveredIdx === idx ? 'var(--text-primary)' : 'var(--text-dim)',
                  fontFamily: 'var(--font-mono)'
                }}>
                  {p.label}
                </span>
              ))}
            </div>
          </div>
        )}

        {viewMode === 'table' && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.8rem',
              textAlign: 'left'
            }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: 'var(--text-dim)' }}>
                  <th style={{ padding: '0.4rem 0.6rem' }}>Segment / Metric</th>
                  <th style={{ padding: '0.4rem 0.6rem' }}>Calculated Value</th>
                  <th style={{ padding: '0.4rem 0.6rem' }}>Relative Share</th>
                  <th style={{ padding: '0.4rem 0.6rem' }}>Detail Context</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p, idx) => (
                  <tr key={idx} style={{
                    borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                    backgroundColor: idx % 2 === 0 ? 'rgba(255, 255, 255, 0.015)' : 'transparent'
                  }}>
                    <td style={{ padding: '0.5rem 0.6rem', color: '#ffffff', fontWeight: 600 }}>{p.label}</td>
                    <td style={{ padding: '0.5rem 0.6rem', fontFamily: 'var(--font-mono)', color: '#93c5fd' }}>
                      {p.value.toLocaleString()}
                    </td>
                    <td style={{ padding: '0.5rem 0.6rem', fontFamily: 'var(--font-mono)', color: 'var(--accent-emerald)' }}>
                      {((p.value / maxVal) * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: '0.5rem 0.6rem', color: 'var(--text-dim)' }}>{p.detail || 'Verified Data'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Caption footer */}
      {caption && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          padding: '0.45rem 1rem',
          backgroundColor: 'rgba(15, 23, 42, 0.4)',
          borderTop: '1px solid rgba(255, 255, 255, 0.04)',
          fontSize: '0.72rem',
          color: 'var(--text-dim)'
        }}>
          <CheckCircle2 size={12} style={{ color: 'var(--accent-emerald)' }} />
          <span>{caption}</span>
        </div>
      )}
    </div>
  );
};
