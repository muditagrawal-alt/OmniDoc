import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { ChartArtifact } from '../../api';
import { ChartFigure } from './ChartFigure';
import { useEscape } from './hooks';
import styles from './ArtifactPanel.module.css';

export type Artifact = { kind: 'chart'; id: string; title: string; chart: ChartArtifact };

interface ArtifactPanelProps {
  artifact: Artifact | null;
  onClose: () => void;
  onCite?: (n: number) => void;
}

/** Side panel (a full-screen sheet on narrow screens) showing one artifact at full size. */
export function ArtifactPanel({ artifact, onClose, onCite }: ArtifactPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const open = artifact !== null;

  useEscape(open, onClose);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
    return () => {
      const opener = openerRef.current;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open, artifact?.id]);

  if (!artifact) return null;

  return (
    <aside className={styles.panel} aria-labelledby={`${artifact.id}-title`}>
      <header className={styles.head}>
        <div className={styles.heading}>
          <span className={styles.kind}>Chart</span>
          <h2 id={`${artifact.id}-title`} className={styles.title}>
            {artifact.title}
          </h2>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" aria-label="Close panel" title="Close (Esc)" onClick={onClose}>
          <X size={18} strokeWidth={1.75} />
        </button>
      </header>
      <div className={styles.body}>
        <ChartFigure key={artifact.id} chart={artifact.chart} variant="full" onCite={onCite} />
      </div>
    </aside>
  );
}
