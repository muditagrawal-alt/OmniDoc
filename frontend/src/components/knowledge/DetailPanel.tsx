import type { JSX, Ref } from 'react';
import { ArrowLeft, ArrowRight, FileText, MessageSquare, X } from 'lucide-react';
import type { GraphModel } from './graphModel';
import { swatchStyle } from './ui';
import styles from './KnowledgeView.module.css';

interface DetailPanelProps {
  model: GraphModel;
  index: number;
  onClose: () => void;
  onNavigate: (index: number) => void;
  onAsk: (name: string) => void;
  panelRef?: Ref<HTMLElement>;
}

/** Right-side (bottom sheet on narrow panes) details for the selected entity. */
export function DetailPanel({ model, index, onClose, onNavigate, onAsk, panelRef }: DetailPanelProps): JSX.Element {
  const entity = model.entities[index];
  const connections = model.connections[index] ?? [];
  const docTitle = entity.docId ? (model.docTitle.get(entity.docId) ?? null) : null;
  const headingId = `kv-detail-${index}`;

  return (
    <aside ref={panelRef} className={`${styles.panel} ${styles.detail}`} aria-labelledby={headingId}>
      <header className={styles.detailHead}>
        <div className={styles.detailHeadText}>
          <p className={styles.detailEyebrow}>
            <span className={styles.swatch} style={swatchStyle(entity.family.cssVar)} aria-hidden="true" />
            <span className={styles.truncate}>{entity.category}</span>
          </p>
          <h2 id={headingId} className={styles.detailName}>
            {entity.name}
          </h2>
        </div>
        <button type="button" className={styles.iconBtn} onClick={onClose} aria-label="Close details" title="Close (Esc)">
          <X size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>

      <div className={styles.detailBody}>
        {entity.description ? (
          <p className={styles.description}>{entity.description}</p>
        ) : (
          <p className={styles.muted}>No description was extracted for this entity.</p>
        )}

        {docTitle && (
          <p className={styles.source}>
            <FileText size={14} strokeWidth={1.75} aria-hidden="true" />
            <span className={styles.sourceKey}>Source</span>
            <span className={styles.sourceTitle} title={docTitle}>
              {docTitle}
            </span>
          </p>
        )}

        <h3 className={styles.sectionTitle}>
          Connections <span className={styles.sectionCount}>{connections.length}</span>
        </h3>
        {connections.length ? (
          <ul className={styles.connList}>
            {connections.map((c) => {
              const rel = model.relations[c.relation];
              const other = model.entities[c.neighbor];
              const Arrow = c.outgoing ? ArrowRight : ArrowLeft;
              const sentence = c.outgoing
                ? `${entity.name} ${rel.relation} ${other.name}`
                : `${other.name} ${rel.relation} ${entity.name}`;
              return (
                <li key={c.relation}>
                  <button
                    type="button"
                    className={styles.conn}
                    onClick={() => onNavigate(c.neighbor)}
                    title={rel.description || sentence}
                    aria-label={`${sentence}. Go to ${other.name}`}
                  >
                    <span className={styles.connRel}>{rel.relation}</span>
                    <Arrow className={styles.connArrow} size={13} strokeWidth={1.75} aria-hidden="true" />
                    <span className={styles.swatch} style={swatchStyle(other.family.cssVar)} aria-hidden="true" />
                    <span className={styles.connName}>{other.name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={styles.muted}>No relations were extracted for this entity.</p>
        )}
      </div>

      <footer className={styles.detailFoot}>
        <button type="button" className={styles.primaryBtn} onClick={() => onAsk(entity.name)}>
          <MessageSquare size={15} strokeWidth={1.75} aria-hidden="true" />
          Ask about this
        </button>
      </footer>
    </aside>
  );
}
