import React from 'react';

interface AudioWaveVisualizerProps {
  active: boolean;
  type: 'listening' | 'speaking';
}

export const AudioWaveVisualizer: React.FC<AudioWaveVisualizerProps> = ({ active, type }) => {
  if (!active) return null;

  const barColor = type === 'listening' ? '#ef4444' : '#3b82f6';
  const label = type === 'listening' ? 'Listening...' : 'Speaking...';

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.45rem',
      padding: '0.25rem 0.65rem',
      backgroundColor: type === 'listening' ? 'rgba(239, 68, 68, 0.12)' : 'rgba(59, 130, 246, 0.12)',
      border: `1px solid ${type === 'listening' ? 'rgba(239, 68, 68, 0.3)' : 'rgba(59, 130, 246, 0.3)'}`,
      borderRadius: 'var(--radius-full)',
      fontSize: '0.72rem',
      fontWeight: 500,
      color: barColor,
      animation: 'fadeIn 0.2s ease-out'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '2px', height: '12px' }}>
        <span style={{ width: '2px', height: '10px', backgroundColor: barColor, borderRadius: '1px', animation: 'pulseGlow 0.6s infinite ease-in-out' }} />
        <span style={{ width: '2px', height: '14px', backgroundColor: barColor, borderRadius: '1px', animation: 'pulseGlow 0.4s infinite ease-in-out', animationDelay: '0.15s' }} />
        <span style={{ width: '2px', height: '8px', backgroundColor: barColor, borderRadius: '1px', animation: 'pulseGlow 0.5s infinite ease-in-out', animationDelay: '0.3s' }} />
        <span style={{ width: '2px', height: '12px', backgroundColor: barColor, borderRadius: '1px', animation: 'pulseGlow 0.45s infinite ease-in-out', animationDelay: '0.1s' }} />
      </div>
      <span>{label}</span>
    </div>
  );
};
