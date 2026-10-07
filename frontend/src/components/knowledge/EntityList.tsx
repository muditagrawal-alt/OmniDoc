import type { JSX } from 'react';
import type { GraphModel } from './graphModel';
import { swatchStyle } from './ui';
import styles from './KnowledgeView.module.css';

interface EntityListProps {
  model: GraphModel;
  /** Entity indices to show, already filtered and ordered. */
  rows: number[];
  selected: number | null;
  onSelect: (index: number) => void;
  note?: string;
}

/** Accessible table twin of the globe: every entity, its category and connection count. */
export function EntityList({ model, rows, selected, onSelect, note }: EntityListProps): JSX.Element {
  return (
    <section className={`${styles.panel} ${styles.listPanel}`} aria-label="Entity list">
      {note && <p className={styles.listNote}>{note}</p>}
      <div className={styles.listScroll}>
        <table className={styles.table}>
          <caption className="visually-hidden">
            Entities in the knowledge graph, most connected first. Choose a name to see its details.
          </caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Category</th>
              <th scope="col" className={styles.numCell}>
                Connections
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => {
              const e = model.entities[i];
              const isSel = selected === i;
              return (
                <tr key={e.id} data-selected={isSel || undefined}>
                  <td className={styles.nameCell}>
                    <button
                      type="button"
                      className={styles.rowBtn}
                      onClick={() => onSelect(i)}
                      aria-current={isSel ? 'true' : undefined}
                    >
                      {e.name}
                    </button>
                  </td>
                  <td>
                    <span className={styles.catCell}>
                      <span className={styles.swatch} style={swatchStyle(e.family.cssVar)} aria-hidden="true" />
                      <span className={styles.truncate}>{e.category}</span>
                    </span>
                  </td>
                  <td className={styles.numCell}>{e.degree}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className={styles.listEmpty}>No entities match the current filters.</p>}
      </div>
    </section>
  );
}
