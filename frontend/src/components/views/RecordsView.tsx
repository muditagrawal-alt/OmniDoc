import { useEffect, useMemo, useState } from 'react';
import { Check, CircleAlert, Download, MinusCircle } from 'lucide-react';
import { api } from '../../api';
import type { LibraryRecord } from '../../api';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { EmptyState, ViewFrame } from './ViewFrame';
import styles from './views.module.css';

type Field = LibraryRecord['fields'][number];

function show(value: unknown): string {
  if (value == null || value === '') return '';
  if (Array.isArray(value)) return value.map(show).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function Checks({ checks }: { checks: LibraryRecord['checks'] }) {
  const failed = checks.filter((c) => c.status === 'fail');
  const passed = checks.filter((c) => c.status === 'pass');
  const title = checks.map((c) => `${c.rule}: ${c.status}${c.message ? ` (${c.message})` : ''}`).join('\n');
  if (failed.length) {
    return <span className={styles.badge} data-tone="bad" title={title}><CircleAlert size={12} strokeWidth={2} /> {failed.length} failed</span>;
  }
  if (passed.length) {
    return <span className={styles.badge} data-tone="good" title={title}><Check size={12} strokeWidth={2.5} /> {passed.length} passed</span>;
  }
  if (checks.length) {
    return <span className={styles.badge} data-tone="muted" title={title}><MinusCircle size={12} strokeWidth={2} /> Not checked</span>;
  }
  return null;
}

function downloadCsv(label: string, columns: string[], rows: string[][]) {
  const cell = (t: string) => (/[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t);
  const text = [columns, ...rows].map((r) => r.map(cell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([`﻿${text}`], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${label}.csv`;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

interface RecordsViewProps {
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
}

/** What each document is and the fields read from it, one table per type, with the consistency checks. */
export function RecordsView({ sidebarOpen, onOpenSidebar, onOpenLibrary }: RecordsViewProps) {
  const [records, setRecords] = useState<LibraryRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  useEffect(() => {
    api.libraryRecords().then((r) => setRecords(r.records)).catch((e: Error) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const out = new Map<string, LibraryRecord[]>();
    for (const r of (records || []).filter((x) => x.extracted && x.fields.length)) out.set(r.label, [...(out.get(r.label) || []), r]);
    return Array.from(out.entries());
  }, [records]);
  const others = (records || []).filter((r) => !r.extracted || !r.fields.length);

  const openField = (r: LibraryRecord, f: Field) =>
    setTarget({ key: `${r.doc_id}-${f.name}-${Date.now()}`, docId: r.doc_id, docTitle: r.document, page: f.page ?? undefined,
      chunkId: f.chunk_id ?? undefined, claim: f.quote ?? undefined, exact: !!f.quote, label: f.label });

  return (
    <ViewFrame
      title="Records"
      description="OmniDoc recognises invoices, receipts, contracts, statements and more, reads their key fields with the page each came from, and checks that they agree (a subtotal and tax that add up to the total)."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      wide
      panel={<SourceViewer target={target} onClose={() => setTarget(null)} />}
    >
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {!records && !error && <p className={styles.note}>Loading…</p>}
      {records && !records.length && (
        <EmptyState title="No documents yet" text="Add documents to the library; each is recognised and its fields read in the background."
          action={<button type="button" className="btn btn-secondary btn-sm" onClick={onOpenLibrary}>Open the library</button>} />
      )}
      {groups.map(([label, items]) => {
        const columns = items[0].fields.map((f) => f.label);
        return (
          <section key={label}>
            <h2 className={styles.groupTitle}>
              {label} <span className={styles.count}>{items.length}</span>
              <button type="button" className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                onClick={() => downloadCsv(label, ['Document', ...columns],
                  items.map((r) => [r.document, ...columns.map((c) => show(r.fields.find((f) => f.label === c)?.value))]))}>
                <Download size={14} strokeWidth={1.75} /> CSV
              </button>
            </h2>
            <div className={styles.gridWrap}>
              <table className={styles.grid}>
                <thead>
                  <tr><th>Document</th>{columns.map((c) => <th key={c}>{c}</th>)}<th>Checks</th></tr>
                </thead>
                <tbody>
                  {items.map((r) => (
                    <tr key={r.doc_id}>
                      <td>{r.document}</td>
                      {columns.map((c) => {
                        const f = r.fields.find((x) => x.label === c);
                        const value = show(f?.value);
                        return (
                          <td key={c}>
                            {f && value ? (
                              <button type="button" onClick={() => openField(r, f)} title={f.page ? `Page ${f.page}` : undefined}>{value}</button>
                            ) : (
                              <span className={styles.missing}>Not found</span>
                            )}
                          </td>
                        );
                      })}
                      <td><Checks checks={r.checks} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      {others.length > 0 && (
        <section>
          <h2 className={styles.groupTitle}>Other documents <span className={styles.count}>{others.length}</span></h2>
          <p className={styles.note} style={{ marginBottom: 'var(--space-3)' }}>
            Types with no field template (reports, letters, papers), or still being read. Ask about them in Chat, or pull any field
            you name with Extract.
          </p>
          <ul className={styles.list}>
            {others.map((r) => (
              <li key={r.doc_id} className={styles.row}>
                <span className={styles.rowMain}><strong>{r.document}</strong></span>
                <span className={styles.badge} data-tone="muted">{r.label}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </ViewFrame>
  );
}
