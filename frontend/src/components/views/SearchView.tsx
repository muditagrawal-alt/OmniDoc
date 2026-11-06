import { Fragment, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { FileText, MessageSquare, Search, Upload } from 'lucide-react';
import { api } from '../../api';
import type { DocumentItem, SearchHit } from '../../api';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { EmptyState, ViewFrame } from './ViewFrame';
import styles from './views.module.css';

interface SearchViewProps {
  documents: DocumentItem[];
  selectedDocIds: string[];
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
  /** Ask the question in a new chat (an answer, which uses a model). */
  onAsk: (question: string) => void;
}

/** The words of the query, marked wherever they appear in a passage. */
function highlight(text: string, query: string): ReactNode {
  const words = Array.from(new Set(query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []));
  if (!words.length) return text;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'giu');
  return text.split(pattern).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>));
}

/** Instant search over every passage of the library: by meaning and by exact words, with no model call. */
export function SearchView({ documents, selectedDocIds, sidebarOpen, onOpenSidebar, onOpenLibrary, onAsk }: SearchViewProps) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searched, setSearched] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [onlySelected, setOnlySelected] = useState(false);
  const [target, setTarget] = useState<ViewerTarget | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const run = useRef(0);

  useEffect(() => inputRef.current?.focus(), []);

  const search = async (text: string) => {
    const q = text.trim();
    if (!q) return;
    const ticket = ++run.current;
    setBusy(true);
    setError(null);
    try {
      const r = await api.search(q, onlySelected ? selectedDocIds : undefined, 20);
      if (ticket !== run.current) return;
      setHits(r.results);
      setSearched(q);
    } catch (e) {
      if (ticket === run.current) setError((e as Error).message);
    } finally {
      if (ticket === run.current) setBusy(false);
    }
  };

  // Results follow the typing, a moment after it pauses.
  useEffect(() => {
    if (query.trim().length < 3) return;
    const t = window.setTimeout(() => void search(query), 350);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, onlySelected]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void search(query);
  };

  return (
    <ViewFrame
      title="Search"
      description="Find passages across your library by meaning and by exact words. It is instant and uses no model, so it does not count toward your free answers."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      panel={<SourceViewer target={target} onClose={() => setTarget(null)} />}
    >
      {!documents.length ? (
        <EmptyState title="Nothing to search yet" text="Add documents to the library, then search them here."
          action={<button type="button" className="btn btn-primary btn-sm" onClick={onOpenLibrary}><Upload size={14} strokeWidth={1.75} /> Add documents</button>} />
      ) : (
        <>
          <form onSubmit={submit} role="search">
            <label className={styles.searchBox}>
              {busy ? <span className="spinner" /> : <Search size={18} strokeWidth={1.75} />}
              <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search your documents"
                placeholder="Search for a figure, a clause, a name…" />
            </label>
          </form>
          <div className={styles.toolbar} style={{ marginTop: 'var(--space-3)' }}>
            {selectedDocIds.length > 0 && (
              <label className="chip" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />
                Only the {selectedDocIds.length} selected {selectedDocIds.length === 1 ? 'document' : 'documents'}
              </label>
            )}
            {hits && <span className={styles.count}>{hits.length} {hits.length === 1 ? 'passage' : 'passages'} for “{searched}”</span>}
            {searched && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onAsk(searched)}>
                <MessageSquare size={14} strokeWidth={1.75} /> Ask OmniDoc instead
              </button>
            )}
          </div>
          {error && <p role="alert" className={styles.error}>{error}</p>}
          {hits && !hits.length && (
            <EmptyState title="No passage matches" text="Try other words, or ask OmniDoc: an answer can combine several pages." />
          )}
          {hits && hits.length > 0 && (
            <ul className={styles.results}>
              {hits.map((h) => (
                <li key={h.chunk_id}>
                  <button type="button" className={styles.result}
                    onClick={() => setTarget({ key: `${h.chunk_id}-${Date.now()}`, docId: h.doc_id, docTitle: h.title, page: h.page,
                      chunkId: h.chunk_id, passage: h.text, label: 'Search result' })}>
                    <span className={styles.resultHead}>
                      <FileText size={14} strokeWidth={1.75} />
                      <span>{h.title}</span>
                      <em>{h.page ? `page ${h.page}` : ''}</em>
                    </span>
                    <span className={styles.resultText}>{highlight(h.text, searched)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!hits && !busy && <p className={styles.note}>Results appear as you type. Click one to see it on its page.</p>}
        </>
      )}
    </ViewFrame>
  );
}
