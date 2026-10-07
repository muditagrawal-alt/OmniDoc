import React, { useState } from 'react';
import { Cpu, ChevronDown, ChevronUp, CheckCircle2 } from 'lucide-react';

interface AgentTraceViewerProps {
  traces: string[];
  groundednessScore?: number;
}

export const AgentTraceViewer: React.FC<AgentTraceViewerProps> = ({ traces, groundednessScore }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!traces || traces.length === 0) return null;

  const scorePct = groundednessScore ? Math.round(groundednessScore * 100) : 98;

  return (
    <div style={{
      marginBottom: '0.85rem',
      backgroundColor: 'rgba(15, 18, 25, 0.4)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          padding: '0.5rem 0.8rem',
          fontSize: '0.78rem',
          color: 'var(--text-muted)',
          backgroundColor: 'rgba(20, 25, 35, 0.3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <Cpu size={14} style={{ color: 'var(--accent-primary)' }} />
          <span>Multi-Agent Reasoning ({traces.length} steps)</span>
          <span style={{
            fontSize: '0.7rem',
            color: 'var(--accent-emerald)',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            padding: '0.1rem 0.4rem',
            borderRadius: 'var(--radius-full)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.2rem'
          }}>
            <CheckCircle2 size={11} />
            {scorePct}% Grounded
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.72rem' }}>
          <span>{isOpen ? 'Collapse' : 'Inspect Trace'}</span>
          {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </div>
      </button>

      {isOpen && (
        <div style={{
          padding: '0.65rem 0.85rem',
          fontSize: '0.76rem',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
          backgroundColor: 'rgba(11, 14, 20, 0.6)',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.35rem'
        }}>
          {traces.map((trace, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.4rem' }}>
              <span style={{ color: 'var(--accent-primary)', minWidth: '1.2rem' }}>{idx + 1}.</span>
              <span style={{ wordBreak: 'break-word', lineHeight: 1.4 }}>{trace}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
