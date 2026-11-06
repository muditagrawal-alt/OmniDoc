import { useState } from 'react';
import { ChevronDown, ChevronRight, Download, ScanSearch, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import type { DocumentItem, SensitiveFinding } from '../../api';
import { useToast } from '../ui/Toast';
import { EmptyState, ViewFrame } from './ViewFrame';
import styles from './views.module.css';

interface Scan {
  status: 'waiting' | 'scanning' | 'done' | 'failed';
  findings?: SensitiveFinding[];
  counts?: Record<string, number>;
  error?: string;
}

interface PrivacyViewProps {
  documents: DocumentItem[];
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
}

/** Scans the whole library for personal and financial identifiers and makes redacted copies. */
export function PrivacyView({ documents, sidebarOpen, onOpenSidebar, onOpenLibrary }: PrivacyViewProps) {
  const toast = useToast();
  const [scans, setScans] = useState<Record<string, Scan>>({});
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [redacting, setRedacting] = useState<string | null>(null);

  const done = Object.values(scans).filter((s) => s.status === 'done' || s.status === 'failed').length;
  const flagged = documents.filter((d) => (scans[d.id]?.findings?.length ?? 0) > 0);
  const totals: Record<string, number> = {};
  for (const s of Object.values(scans)) for (const [k, v] of Object.entries(s.counts || {})) totals[k] = (totals[k] || 0) + v;

  const scanAll = async () => {
    setRunning(true);
    setScans(Object.fromEntries(documents.map((d) => [d.id, { status: 'waiting' } as Scan])));
    for (const d of documents) {
      setScans((s) => ({ ...s, [d.id]: { status: 'scanning' } }));
      try {
        const r = await api.getSensitive(d.id);
        setScans((s) => ({ ...s, [d.id]: { status: 'done', findings: r.findings, counts: r.counts } }));
      } catch (e) {
        setScans((s) => ({ ...s, [d.id]: { status: 'failed', error: (e as Error).message } }));
      }
    }
    setRunning(false);
  };

  const redact = async (d: DocumentItem) => {
    setRedacting(d.id);
    try {
      const { blob, filename } = await api.redact(d.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setRedacting(null);
    }
  };

  return (
    <ViewFrame
      title="Privacy scan"
      description="Find Aadhaar (checksum-verified), PAN, GSTIN, IFSC, card, passport and phone numbers across the whole library, then download copies with them removed: the text is taken out, not covered."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      actions={documents.length ? (
        <button type="button" className="btn btn-primary" onClick={scanAll} disabled={running}>
          {running ? <span className="spinner" /> : <ScanSearch size={15} strokeWidth={1.75} />}
          {running ? `Scanning ${done + 1} of ${documents.length}` : done ? 'Scan again' : 'Scan the library'}
        </button>
      ) : undefined}
    >
      {!documents.length && (
        <EmptyState title="No documents yet" text="Add documents to the library, then scan them here."
          action={<button type="button" className="btn btn-secondary btn-sm" onClick={onOpenLibrary}>Open the library</button>} />
      )}
      {documents.length > 0 && !Object.keys(scans).length && (
        <EmptyState title="Nothing scanned yet"
          text="The scan reads every page, scans included, on this server. Values are shown masked; nothing is sent to a model." />
      )}
      {Object.keys(scans).length > 0 && (
        <>
          <div className={styles.progress} aria-hidden="true"><span style={{ width: `${(done / Math.max(1, documents.length)) * 100}%` }} /></div>
          <div className={styles.toolbar} style={{ marginTop: 'var(--space-4)' }}>
            {!running && !flagged.length && (
              <span className={styles.badge} data-tone="good"><ShieldCheck size={12} strokeWidth={2} /> Nothing found in {done} documents</span>
            )}
            {Object.entries(totals).map(([k, v]) => <span key={k} className={styles.badge} data-tone="accent">{k}: {v}</span>)}
          </div>
          <ul className={styles.list}>
            {documents.map((d) => {
              const scan = scans[d.id];
              const count = scan?.findings?.length ?? 0;
              const expanded = open === d.id && count > 0;
              return (
                <li key={d.id}>
                  <div className={styles.row}>
                    <button type="button" className={styles.rowMain} style={{ textAlign: 'left' }} disabled={!count}
                      aria-expanded={count ? expanded : undefined} onClick={() => setOpen(expanded ? null : d.id)}>
                      <strong>{count > 0 && (expanded ? <ChevronDown size={14} strokeWidth={1.75} /> : <ChevronRight size={14} strokeWidth={1.75} />)} {d.filename}</strong>
                      <span>
                        {scan?.status === 'waiting' && 'Waiting'}
                        {scan?.status === 'scanning' && 'Scanning…'}
                        {scan?.status === 'failed' && (scan.error || 'Could not scan')}
                        {scan?.status === 'done' && (count
                          ? Object.entries(scan.counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ')
                          : 'Nothing found')}
                      </span>
                    </button>
                    <span className={styles.rowMeta}>
                      {count > 0 && (
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => redact(d)} disabled={redacting === d.id}>
                          {redacting === d.id ? <span className="spinner" /> : <Download size={14} strokeWidth={1.75} />} Redacted copy
                        </button>
                      )}
                    </span>
                  </div>
                  {expanded && (
                    <div className={styles.expanded}>
                      <ul className={styles.findings}>
                        {scan!.findings!.map((f, i) => (
                          <li key={i}>
                            <span>{f.label}</span>
                            <span className={styles.count}>p. {f.page}</span>
                            <code>{f.context || f.masked}</code>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </ViewFrame>
  );
}
