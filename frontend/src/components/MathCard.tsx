import React, { useEffect, useRef, useState } from 'react';
import katex from 'katex';
import { Calculator, CheckCircle2, Copy, Check } from 'lucide-react';
import type { MathResult } from '../api';

interface MathCardProps {
  math: MathResult;
}

export const MathCard: React.FC<MathCardProps> = ({ math }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (containerRef.current && math.expression) {
      try {
        // Strip markdown backticks if present
        let cleanExpr = math.expression.replace(/`/g, '').trim();
        katex.render(cleanExpr, containerRef.current, {
          displayMode: true,
          throwOnError: false,
        });
      } catch (e) {
        if (containerRef.current) {
          containerRef.current.innerText = math.expression;
        }
      }
    }
  }, [math.expression]);

  const handleCopy = () => {
    navigator.clipboard.writeText(`${math.expression} = ${math.result}${math.unit ? ' ' + math.unit : ''}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{
      margin: '0.85rem 0',
      backgroundColor: 'rgba(21, 25, 34, 0.7)',
      border: '1px solid rgba(59, 130, 246, 0.25)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      boxShadow: 'var(--shadow-sm)'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.6rem 0.9rem',
        backgroundColor: 'rgba(30, 41, 59, 0.4)',
        borderBottom: '1px solid rgba(59, 130, 246, 0.15)',
        fontSize: '0.8rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#93c5fd', fontWeight: 500 }}>
          <Calculator size={14} />
          <span>Deterministic Mathematical Execution</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {math.verified && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: 'var(--accent-emerald)', fontSize: '0.75rem' }}>
              <CheckCircle2 size={13} />
              <span>SymPy Verified</span>
            </div>
          )}
          <button
            onClick={handleCopy}
            title="Copy formula and result"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
              color: 'var(--text-muted)',
              fontSize: '0.75rem',
              padding: '0.2rem 0.45rem',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
            }}
          >
            {copied ? <Check size={12} style={{ color: 'var(--accent-emerald)' }} /> : <Copy size={12} />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>
      </div>

      {/* LaTeX Formula Rendering */}
      <div style={{ padding: '0.75rem 1rem' }}>
        <div ref={containerRef} style={{ overflowX: 'auto', textAlign: 'center' }} />
        
        {/* Outcome Box */}
        <div style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'center',
          gap: '0.5rem',
          marginTop: '0.5rem',
          padding: '0.4rem 0.75rem',
          backgroundColor: 'rgba(15, 23, 42, 0.6)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-subtle)',
        }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Calculated Outcome:</span>
          <span style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {typeof math.result === 'number' ? (Number.isInteger(math.result) ? math.result : math.result.toFixed(4)) : math.result}
            {math.unit && <span style={{ fontSize: '0.85rem', color: '#93c5fd', marginLeft: '0.35rem' }}>{math.unit}</span>}
          </span>
        </div>
      </div>
    </div>
  );
};
