import { useId, type JSX } from 'react';
import { ChevronDown } from 'lucide-react';
import type { FamilyCount } from './graphModel';
import { swatchStyle } from './ui';
import styles from './KnowledgeView.module.css';

interface LegendProps {
  items: FamilyCount[];
  hidden: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onShowAll: () => void;
  onIsolate: (key: string | null) => void;
  collapsible: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Families present in the graph with counts. Click toggles visibility, hover
 * or focus isolates the family on the globe (colour always has a label here).
 */
export function Legend({
  items,
  hidden,
  onToggle,
  onShowAll,
  onIsolate,
  collapsible,
  open,
  onOpenChange,
}: LegendProps): JSX.Element {
  const listId = useId();
  const expanded = !collapsible || open;
  const hiddenCount = items.filter((i) => hidden.has(i.family.key)).length;

  return (
    <section className={`${styles.panel} ${styles.legend}`} aria-label="Categories">
      <div className={styles.legendHead}>
        {collapsible ? (
          <button
            type="button"
            className={styles.legendToggle}
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => onOpenChange(!open)}
          >
            Categories
            <ChevronDown
              size={14}
              strokeWidth={1.75}
              aria-hidden="true"
              className={open ? styles.chevronOpen : styles.chevron}
            />
          </button>
        ) : (
          <span className={styles.legendTitle}>Categories</span>
        )}
        {hiddenCount > 0 && expanded && (
          <button type="button" className={styles.textBtn} onClick={onShowAll}>
            Show all
          </button>
        )}
      </div>
      {expanded && (
        <ul id={listId} className={styles.legendList} onMouseLeave={() => onIsolate(null)}>
          {items.map(({ family, count }) => {
            const on = !hidden.has(family.key);
            return (
              <li key={family.key}>
                <button
                  type="button"
                  className={styles.legendItem}
                  aria-pressed={on}
                  title={on ? `Hide ${family.label.toLowerCase()}` : `Show ${family.label.toLowerCase()}`}
                  onClick={() => {
                    if (on) onIsolate(null);
                    onToggle(family.key);
                  }}
                  onMouseEnter={() => onIsolate(on ? family.key : null)}
                  onFocus={() => onIsolate(on ? family.key : null)}
                  onBlur={() => onIsolate(null)}
                >
                  <span className={styles.swatch} style={swatchStyle(family.cssVar)} aria-hidden="true" />
                  <span className={styles.legendLabel}>{family.label}</span>
                  <span className={styles.legendCount}>{count.toLocaleString()}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
