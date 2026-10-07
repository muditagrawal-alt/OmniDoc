import React, { useState } from 'react';
import { BookOpen, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import type { EvidenceSource } from '../api';

interface EvidenceCardProps {
  sources: EvidenceSource[];
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({ sources }) => {
  const [expanded, setExpanded] = useState(false);

  if (!sources || sources.length === 0) return null;

  return (
    <div style={{
      margin: '0.85rem 0',
      backgroundColor: 'rgba(19, 23, 31, 0.6)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          padding: '0.65rem 0.9rem',
          backgroundColor: 'rgba(26, 32, 44, 0.4)',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BookOpen size={14} style={{ color: 'var(--accent-primary)' }} />
          <span style={{ fontWeight: 500 }}>
            {sources.length} Grounded Source Citation{sources.length > 1 ? 's' : ''}
          </span>
          <span style={{
            fontSize: '0.72rem',
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            color: '#93c5fd',
            padding: '0.15rem 0.45rem',
            borderRadius: 'var(--radius-full)',
            border: '1px solid rgba(59, 130, 246, 0.25)'
          }}>
            LanceDB + Kùzu
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-muted)' }}>
          <span>{expanded ? 'Hide' : 'Inspect'}</span>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* Expanded Sources Grid */}
      {expanded && (
        <div style={{
          padding: '0.75rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '0.65rem',
          backgroundColor: 'rgba(15, 18, 25, 0.5)',
          animation: 'fadeIn 0.15s ease-out'
        }}>
          {sources.map((src, i) => (
            <div
              key={i}
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '0.65rem 0.8rem',
                fontSize: '0.8rem',
              }}
            >
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '0.35rem'
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.74rem',
                  color: 'var(--text-muted)',
                }}>
                  {src.chunk_id ? `[${src.chunk_id}]` : `Source #${i + 1}`}
                </span>
                <span style={{
                  fontSize: '0.72rem',
                  color: 'var(--accent-emerald)',
                  fontWeight: 600,
                  backgroundColor: 'rgba(16, 185, 129, 0.1)',
                  padding: '0.1rem 0.35rem',
                  borderRadius: 'var(--radius-sm)'
                }}>
                  {Math.round(src.score * 100)}% Match
                </span>
              </div>
              <p style={{
                color: 'var(--text-secondary)',
                lineHeight: 1.45,
                fontSize: '0.78rem',
                display: '-webkit-box',
                WebkitLineClamp: 3,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}>
                {src.snippet}
              </p>
              {src.doc_id && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  marginTop: '0.4rem',
                  fontSize: '0.72rem',
                  color: 'var(--text-dim)'
                }}>
                  <ExternalLink size={10} />
                  <span>Doc: {src.doc_id}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
