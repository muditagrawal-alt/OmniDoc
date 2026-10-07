import { useId, useState } from 'react';
import type { Source } from '../../api';
import styles from './Markdown.module.css';

interface CitationProps {
  n: number;
  source?: Source;
  onCite?: (n: number) => void;
}

export function sourceLabel(s?: Source): string {
  if (!s) return '';
  if (s.kind === 'graph') return s.title || 'Knowledge graph';
  if (s.kind === 'math') return s.title || 'Calculation';
  return s.doc_title || s.title || s.doc_id || 'Document';
}

/** Inline [n] citation: hover or focus previews the passage, click jumps to the source. */
export function Citation({ n, source, onCite }: CitationProps) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  return (
    <span className={styles.citeWrap} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className={styles.cite}
        aria-describedby={source && open ? tipId : undefined}
        aria-label={source ? `Source ${n}: ${sourceLabel(source)}` : `Source ${n}`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => onCite?.(n)}
      >
        {n}
      </button>
      {open && source && (
        <span role="tooltip" id={tipId} className={styles.citeTip}>
          <span className={styles.citeTipTitle}>
            {sourceLabel(source)}
            {source.page != null && <span className={styles.citeTipMeta}> · p. {source.page}</span>}
          </span>
          {source.section && <span className={styles.citeTipMeta}>{source.section}</span>}
          <span className={styles.citeTipSnippet}>{source.snippet}</span>
        </span>
      )}
    </span>
  );
}
