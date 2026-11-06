import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api';
import type { DocumentItem, TimelineEvent } from '../../api';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { EmptyState, ViewFrame } from './ViewFrame';
import styles from './views.module.css';

interface TimelineViewProps {
  documents: DocumentItem[];
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
}

/** Every dated statement in the library in date order, grouped by year, each linked to its page. */
export function TimelineView({ documents, sidebarOpen, onOpenSidebar, onOpenLibrary }: TimelineViewProps) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [docId, setDocId] = useState('');
  const [filter, setFilter] = useState('');
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  useEffect(() => {
    let live = true;
    api.timeline(docId ? [docId] : undefined)
      .then((r) => {
        if (!live) return;
        setEvents(r.events);
        setTotal(r.total);
        setError(null);
      })
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [docId]);

  const years = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const out = new Map<string, TimelineEvent[]>();
    for (const e of (events || []).filter((x) => !q || x.text.toLowerCase().includes(q) || x.document.toLowerCase().includes(q))) {
      const year = e.date.slice(0, 4);
      out.set(year, [...(out.get(year) || []), e]);
    }
    return Array.from(out.entries());
  }, [events, filter]);

  return (
    <ViewFrame
      title="Timeline"
      description="Every sentence in your library that mentions a date, in date order: deadlines, filings, effective dates and results. Read from the documents themselves, with no model call."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      panel={<SourceViewer target={target} onClose={() => setTarget(null)} />}
    >
      {!documents.length ? (
        <EmptyState title="No documents yet" text="Dates in the documents you add appear here in order."
          action={<button type="button" className="btn btn-secondary btn-sm" onClick={onOpenLibrary}>Open the library</button>} />
      ) : (
        <>
          <div className={styles.toolbar}>
            <select className="field" value={docId} onChange={(e) => setDocId(e.target.value)} aria-label="Document" style={{ maxWidth: 280 }}>
              <option value="">All documents</option>
              {documents.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
            <input className={`field ${styles.filter}`} value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by words" aria-label="Filter the timeline" />
            {events && <span className={styles.count}>{total > events.length ? `${events.length} of ${total}` : events.length} dated statements</span>}
          </div>
          {error && <p role="alert" className={styles.error}>{error}</p>}
          {!events && !error && <p className={styles.note}>Reading the dates…</p>}
          {events && !events.length && <EmptyState title="No dates found" text="None of these documents mentions a date OmniDoc can read." />}
          {years.map(([year, items]) => (
            <section key={year}>
              <h2 className={styles.year}>{year}</h2>
              <ol className={styles.events}>
                {items.map((e, i) => (
                  <li key={`${e.chunk_id}-${e.date}-${i}`}>
                    <button type="button" className={styles.event}
                      onClick={() => setTarget({ key: `${e.chunk_id}-${Date.now()}`, docId: e.doc_id, docTitle: e.document, page: e.page,
                        chunkId: e.chunk_id, claim: e.text, exact: true, label: e.written })}>
                      <span className={styles.eventDate}>{e.written}</span>
                      <span className={styles.eventBody}>
                        <p>{e.text}</p>
                        <span>{e.document}{e.page ? `, page ${e.page}` : ''}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </>
      )}
    </ViewFrame>
  );
}
