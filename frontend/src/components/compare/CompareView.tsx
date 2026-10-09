import { useMemo, useState } from 'react';
import { ArrowLeftRight, PanelLeftOpen, ScanSearch, Sparkles } from 'lucide-react';
import { api } from '../../api';
import type { CompareChange, CompareResult, DocumentItem } from '../../api';
import { pluralize } from '../../lib/format';
import { Markdown } from '../chat/Markdown';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import styles from './CompareView.module.css';

interface CompareViewProps {
  documents: DocumentItem[];
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
}

type Filter = 'all' | 'figures' | 'modified' | 'added' | 'removed';
let opened = 0;

function DiffText({ change, side }: { change: CompareChange; side: 'a' | 'b' }) {
  if (change.kind !== 'modified' || !change.diff) return <>{(side === 'a' ? change.a : change.b)?.text}</>;
  return (
    <>
      {change.diff.map(([op, text], i) =>
        op === '=' ? (
          <span key={i}>{text}</span>
        ) : op === '-' && side === 'a' ? (
          <del key={i}>{text}</del>
        ) : op === '+' && side === 'b' ? (
          <ins key={i}>{text}</ins>
        ) : null,
      )}
    </>
  );
}

export function CompareView({ documents, sidebarOpen, onOpenSidebar }: CompareViewProps) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [result, setResult] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState<'compare' | 'summary' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);

  const run = async (summarize: boolean) => {
    if (!a || !b || a === b) return;
    setBusy(summarize ? 'summary' : 'compare');
    setError(null);
    try {
      const r = await api.compare(a, b, summarize);
      setResult(r);
      if (!summarize) setFilter('all');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const shown = useMemo(() => {
    const changes = result?.changes ?? [];
    if (filter === 'figures') return changes.filter((c) => c.figures && c.figures.length);
    if (filter === 'all') return changes;
    return changes.filter((c) => c.kind === filter);
  }, [result, filter]);

  const open = (side: 'a' | 'b', change: CompareChange) => {
    const s = side === 'a' ? change.a : change.b;
    const doc = side === 'a' ? result?.a : result?.b;
    if (!s || !doc) return;
    setViewer({ key: `${change.id}-${side}-${++opened}`, docId: doc.id, docTitle: doc.title, page: s.page, chunkId: s.chunk_id,
                claim: s.text, exact: true, label: `${change.id} · ${side === 'a' ? 'A' : 'B'}` });
  };

  const counts: Record<Filter, number> = {
    all: result?.changes.length ?? 0,
    figures: result?.stats.figures ?? 0,
    modified: result?.stats.modified ?? 0,
    added: result?.stats.added ?? 0,
    removed: result?.stats.removed ?? 0,
  };

  return (
    <div className={styles.layout} data-panel={!!viewer}>
      <div className={styles.page}>
        <header className={styles.topbar}>
          {!sidebarOpen && (
            <button type="button" className="icon-btn" onClick={onOpenSidebar} aria-label="Open sidebar">
              <PanelLeftOpen size={18} strokeWidth={1.75} />
            </button>
          )}
        </header>
        <main className={styles.content} id="main">
          <h1 className={styles.title}>Compare</h1>
          <p className={styles.subtitle}>
            See what changed between two versions of a document: reworded clauses, changed figures, and added or removed text.
          </p>

          <section className={styles.pickers} aria-label="Documents to compare">
            <label className={styles.picker}>
              <span>A (earlier)</span>
              <select className="field" value={a} onChange={(e) => setA(e.target.value)}>
                <option value="">Choose a document</option>
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="icon-btn" aria-label="Swap A and B" title="Swap" onClick={() => { setA(b); setB(a); }}>
              <ArrowLeftRight size={16} strokeWidth={1.75} />
            </button>
            <label className={styles.picker}>
              <span>B (later)</span>
              <select className="field" value={b} onChange={(e) => setB(e.target.value)}>
                <option value="">Choose a document</option>
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn-primary" disabled={!a || !b || a === b || !!busy} onClick={() => run(false)}>
              {busy === 'compare' && <span className="spinner" />} Compare
            </button>
          </section>
          {error && <p className={styles.error} role="alert">{error}</p>}

          {result && (
            <section className={styles.results} aria-label="Changes">
              <div className={styles.statsRow}>
                <span className={styles.similarity}>{Math.round(result.stats.similarity * 100)}% the same</span>
                <div className={styles.filters} role="radiogroup" aria-label="Show">
                  {(['all', 'figures', 'modified', 'added', 'removed'] as Filter[]).map((f) => (
                    <button key={f} type="button" role="radio" aria-checked={filter === f} className="chip" onClick={() => setFilter(f)}>
                      {f === 'all' ? 'All changes' : f === 'figures' ? 'Changed figures' : f[0].toUpperCase() + f.slice(1)}
                      <span className="num">{counts[f]}</span>
                    </button>
                  ))}
                </div>
                <span className={styles.grow} />
                <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy || !result.changes.length} onClick={() => run(true)}>
                  {busy === 'summary' ? <span className="spinner" /> : <Sparkles size={14} strokeWidth={1.9} />} Summarize changes
                </button>
              </div>
              {result.summary && (
                <div className={styles.summary}>
                  <Markdown text={result.summary} />
                </div>
              )}
              {result.summary_error && <p className={styles.error}>{result.summary_error}</p>}
              {!result.changes.length && <p className={styles.subtitle}>The two documents say the same thing.</p>}
              <ol className={styles.changes}>
                {shown.map((c) => (
                  <li key={c.id} className={styles.change} data-kind={c.kind}>
                    <div className={styles.changeHead}>
                      <span className={styles.changeId}>{c.id}</span>
                      <span className={styles.kind} data-kind={c.kind}>{c.kind}</span>
                      {c.figures?.map((f, i) => (
                        <span key={i} className={styles.figure}>
                          {f.from.toLocaleString()} → {f.to.toLocaleString()}
                        </span>
                      ))}
                    </div>
                    <div className={styles.sides}>
                      <div className={styles.side} data-empty={!c.a || undefined}>
                        {c.a ? (
                          <>
                            <p><DiffText change={c} side="a" /></p>
                            <button type="button" className={styles.pageLink} onClick={() => open('a', c)}>
                              <ScanSearch size={12} strokeWidth={2} /> A · p. {c.a.page}
                            </button>
                          </>
                        ) : (
                          <span className={styles.none}>Not in A</span>
                        )}
                      </div>
                      <div className={styles.side} data-empty={!c.b || undefined}>
                        {c.b ? (
                          <>
                            <p><DiffText change={c} side="b" /></p>
                            <button type="button" className={styles.pageLink} onClick={() => open('b', c)}>
                              <ScanSearch size={12} strokeWidth={2} /> B · p. {c.b.page}
                            </button>
                          </>
                        ) : (
                          <span className={styles.none}>Not in B</span>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              {shown.length === 0 && result.changes.length > 0 && <p className={styles.subtitle}>{pluralize(0, 'change')} of this kind.</p>}
            </section>
          )}
        </main>
      </div>
      <SourceViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
