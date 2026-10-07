import React from 'react';
import { AlertTriangle, CheckCircle } from 'lucide-react';
import type { ConflictItem } from '../api';

interface ConflictBannerProps {
  conflicts: ConflictItem[];
}

export const ConflictBanner: React.FC<ConflictBannerProps> = ({ conflicts }) => {
  if (!conflicts || conflicts.length === 0) return null;

  return (
    <div style={{
      margin: '0.85rem 0',
      backgroundColor: 'rgba(245, 158, 11, 0.08)',
      border: '1px solid rgba(245, 158, 11, 0.3)',
      borderRadius: 'var(--radius-lg)',
      padding: '0.85rem 1rem',
      fontSize: '0.82rem',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        color: '#fbbf24',
        fontWeight: 600,
        marginBottom: '0.5rem',
      }}>
        <AlertTriangle size={15} />
        <span>Cross-Document Conflict Resolution Detected ({conflicts.length})</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
        {conflicts.map((c, i) => (
          <div
            key={i}
            style={{
              backgroundColor: 'rgba(15, 20, 28, 0.5)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '0.6rem 0.75rem',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
              Entity: {c.entity}
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '0.5rem',
              color: 'var(--text-muted)',
              fontSize: '0.76rem',
              marginBottom: '0.4rem',
            }}>
              <div>
                <span style={{ color: 'var(--text-dim)' }}>Source A ({c.source_a || 'Primary'}): </span>
                <span style={{ color: 'var(--text-secondary)' }}>{c.claim_a}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-dim)' }}>Source B ({c.source_b || 'Secondary'}): </span>
                <span style={{ color: 'var(--text-secondary)' }}>{c.claim_b}</span>
              </div>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              color: 'var(--accent-emerald)',
              fontSize: '0.78rem',
              borderTop: '1px solid var(--border-subtle)',
              paddingTop: '0.35rem',
            }}>
              <CheckCircle size={13} />
              <span>Resolved: {c.resolution}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
