import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Download, FileSearch, Table2 } from 'lucide-react';
import { api } from '../../api';
import type { LibraryTable, TableData } from '../../api';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { EmptyState, ViewFrame } from './ViewFrame';
import styles from './views.module.css';

const MAX_ROWS = 1000;

function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv(name: string, columns: string[], rows: unknown[][]) {
  const lines = [columns, ...rows].map((r) => r.map(csvCell).join(','));
  const url = URL.createObjectURL(new Blob([`﻿${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${name.replace(/[\\/:*?"<>|]+/g, '').trim() || 'table'}.csv`;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function TableRows({ entry, onOpen }: { entry: LibraryTable; onOpen: () => void }) {
  const [data, setData] = useState<TableData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.getDocumentTable(entry.doc_id, entry.table, MAX_ROWS)
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [entry.doc_id, entry.table]);

  if (error) return <p role="alert" className={styles.error}>{error}</p>;
  if (!data) return <p className={styles.note}>Loading the rows…</p>;
  return (
    <>
      <div className={styles.gridWrap}>
        <table className={styles.grid}>
          <thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>{(r as unknown[]).map((v, j) => <td key={j}>{v == null ? '' : String(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.actions}>
        <button type="button" className="btn btn-secondary btn-sm"
          onClick={() => downloadCsv(`${entry.document} - ${entry.title || entry.table}`, data.columns, data.rows as unknown[][])}>
          <Download size={14} strokeWidth={1.75} /> Download CSV
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onOpen}>
          <FileSearch size={14} strokeWidth={1.75} /> Show it in the document
        </button>
        {entry.n_rows > data.rows.length && (
          <span className={styles.note}>Showing the first {data.rows.length.toLocaleString()} of {entry.n_rows.toLocaleString()} rows.</span>
        )}
      </div>
    </>
  );
}

interface TablesViewProps {
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
}

/** Every table found in the library, as data: open one as a grid, download it, or see it on its page. */
export function TablesView({ sidebarOpen, onOpenSidebar, onOpenLibrary }: TablesViewProps) {
  const [tables, setTables] = useState<LibraryTable[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  useEffect(() => {
    api.libraryTables().then((r) => setTables(r.tables)).catch((e: Error) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const shown = (tables || []).filter((t) => !q || [t.document, t.title, t.table, ...t.columns].join(' ').toLowerCase().includes(q));
    const out = new Map<string, LibraryTable[]>();
    for (const t of shown) out.set(t.document, [...(out.get(t.document) || []), t]);
    return Array.from(out.entries());
  }, [tables, filter]);

  return (
    <ViewFrame
      title="Tables"
      description="Every table OmniDoc found in your documents, kept as data: the same tables it adds up and compares when you ask about figures."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      wide
      panel={<SourceViewer target={target} onClose={() => setTarget(null)} />}
    >
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {!tables && !error && <p className={styles.note}>Loading…</p>}
      {tables && !tables.length && (
        <EmptyState title="No tables yet" text="Tables in PDFs, scans, spreadsheets and slides appear here once those documents are in the library."
          action={<button type="button" className="btn btn-secondary btn-sm" onClick={onOpenLibrary}>Open the library</button>} />
      )}
      {tables && tables.length > 0 && (
        <>
          <div className={styles.toolbar}>
            <input className={`field ${styles.filter}`} value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by document, title or column" aria-label="Filter tables" />
            <span className={styles.count}>{tables.length} {tables.length === 1 ? 'table' : 'tables'}</span>
          </div>
          {groups.map(([doc, items]) => (
            <section key={doc}>
              <h2 className={styles.groupTitle}>{doc} <span className={styles.count}>{items.length}</span></h2>
              <ul className={styles.list}>
                {items.map((t) => {
                  const id = `${t.doc_id}/${t.table}`;
                  const expanded = open === id;
                  return (
                    <li key={id}>
                      <button type="button" className={styles.row} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : id)}>
                        <span className={styles.rowMain}>
                          <strong><Table2 size={14} strokeWidth={1.75} /> {t.title || t.table}</strong>
                          <span>{t.columns.slice(0, 6).join(' · ')}{t.columns.length > 6 ? ` and ${t.columns.length - 6} more` : ''}</span>
                        </span>
                        <span className={styles.rowMeta}>
                          {t.page ? `page ${t.page}` : ''} <span>{t.n_rows} × {t.columns.length}</span>
                          {expanded ? <ChevronDown size={16} strokeWidth={1.75} /> : <ChevronRight size={16} strokeWidth={1.75} />}
                        </span>
                      </button>
                      {expanded && (
                        <div className={styles.expanded}>
                          <TableRows entry={t} onOpen={() => setTarget({ key: `${id}-${Date.now()}`, docId: t.doc_id, docTitle: t.document,
                            page: t.page, table: t.table, label: t.title || 'Table' })} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </>
      )}
    </ViewFrame>
  );
}
