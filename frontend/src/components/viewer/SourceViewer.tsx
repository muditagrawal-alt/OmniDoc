import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronUp, CircleDashed, ExternalLink, Globe2, Highlighter, Minus, Plus, RefreshCw, ScanText, X } from 'lucide-react';
import { api } from '../../api';
import type { DocumentInfo, DocumentRecord, DocumentSummary, DocumentText, LocateResult, SensitiveFinding, TableData, WebPage } from '../../api';
import { pluralize } from '../../lib/format';
import { useElementSize, useEscape } from '../artifacts/hooks';
import styles from './SourceViewer.module.css';

/** What to show: a cited passage (and the claim it supports) in its document. */
export interface ViewerTarget {
  /** New on every click, so the same citation can be shown (and flashed) again */
  key: string;
  docId: string;
  docTitle?: string;
  page?: number | null;
  chunkId?: string;
  /** The answer sentence that cites the passage; the viewer highlights the passage sentence that supports it */
  claim?: string;
  /** Passage text, used when there is no chunk id to look up */
  passage?: string;
  /** SQL table the figures were computed from, and the query */
  table?: string;
  sql?: string;
  /** Highlight the claim itself (a verbatim quote) instead of the sentence that best supports it */
  exact?: boolean;
  /** Header label, e.g. "Source 3" or "Invoice number" */
  label?: string;
  /** A web page (cited web result): read on the server and shown in the reader */
  url?: string;
}

// A highlight shows for about 2.6 s, then fades (--flash in SourceViewer.module.css).
// Widths the server renders pages at (it snaps to the nearest).
const PAGE_WIDTHS = [400, 700, 1000, 1400, 2000];
const ZOOMS = [1, 1.25, 1.5, 2];
const SPREADSHEETS = new Set(['csv', 'tsv', 'xlsx']);

const infoCache = new Map<string, Promise<DocumentInfo>>();
const textCache = new Map<string, Promise<DocumentText>>();

function cached<T>(cache: Map<string, Promise<T>>, key: string, load: () => Promise<T>): Promise<T> {
  let p = cache.get(key);
  if (!p) {
    p = load();
    cache.set(key, p);
    p.catch(() => cache.delete(key));
  }
  return p;
}

type Rect = [number, number, number, number];

const rectStyle = ([x0, y0, x1, y1]: Rect): CSSProperties => ({
  left: `${x0 * 100}%`,
  top: `${y0 * 100}%`,
  width: `${(x1 - x0) * 100}%`,
  height: `${(y1 - y0) * 100}%`,
});

/** A bar in the page margin beside the highlighted lines; it stays after the highlight fades. */
function marginStyle(rects: Rect[]): CSSProperties {
  const top = Math.min(...rects.map((r) => r[1]));
  const bottom = Math.max(...rects.map((r) => r[3]));
  const left = Math.min(...rects.map((r) => r[0]));
  return { top: `${top * 100}%`, height: `${(bottom - top) * 100}%`, left: `${Math.max(0.4, left * 100 - 2.2)}%` };
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Character range of the quote in the passage, tolerant of whitespace and punctuation differences. */
function findQuote(text: string, quote?: string): [number, number] | null {
  if (!quote) return null;
  const i = text.indexOf(quote);
  if (i >= 0) return [i, i + quote.length];
  const words = quote.match(/[\p{L}\p{N}]+/gu);
  if (!words || words.length < 2) return null;
  const m = new RegExp(words.map(escapeRe).join('[^\\p{L}\\p{N}]+'), 'iu').exec(text);
  return m ? [m.index, m.index + m[0].length] : null;
}

const LANGUAGE_LABELS: Record<string, string> = {
  eng: 'English', hin: 'Hindi', mar: 'Marathi', tam: 'Tamil', tel: 'Telugu', kan: 'Kannada', ben: 'Bengali',
  guj: 'Gujarati', pan: 'Punjabi', mal: 'Malayalam', ori: 'Odia', asm: 'Assamese', urd: 'Urdu', ara: 'Arabic',
  chi_sim: 'Chinese', jpn: 'Japanese', kor: 'Korean', rus: 'Russian', fra: 'French', deu: 'German', spa: 'Spanish',
};

function languageLabel(code?: string | null): string {
  if (!code) return '';
  return code
    .split('+')
    .map((c) => LANGUAGE_LABELS[c] || c)
    .filter((v, i, a) => a.indexOf(v) === i)
    .join(', ');
}

/* -------------------------------------------------------------------- panel */

interface SourceViewerProps {
  target: ViewerTarget | null;
  onClose: () => void;
}

/** Side panel (a full-screen sheet on narrow screens) showing a cited passage in its document. */
export function SourceViewer({ target, onClose }: SourceViewerProps) {
  if (!target) return null;
  if (target.url) return <WebPanel key={target.url} target={target} onClose={onClose} />;
  // One panel per document: switching documents starts fresh, a new citation in the same one keeps zoom and tab.
  return <ViewerPanel key={target.docId} target={target} onClose={onClose} />;
}

function ViewerPanel({ target, onClose }: { target: ViewerTarget; onClose: () => void }) {
  const { docId, page: targetPage, chunkId, claim, passage, table, exact } = target;
  // Opened from the library rather than from a citation: nothing to locate or highlight.
  const browsing = !chunkId && !claim && !table && !passage;
  const [info, setInfo] = useState<DocumentInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loc, setLoc] = useState<LocateResult | null>(null);
  const [locating, setLocating] = useState(!browsing);
  const [flash, setFlash] = useState(0);
  const [tab, setTab] = useState<'document' | 'summary' | 'details' | 'privacy'>('document');
  const [zoom, setZoom] = useState(1);
  const [mode, setMode] = useState<'table' | 'text' | null>(null);
  const [shownKey, setShownKey] = useState(target.key);
  const closeRef = useRef<HTMLButtonElement>(null);

  // A new citation: back to the document, and wait for its location.
  if (shownKey !== target.key) {
    setShownKey(target.key);
    setTab('document');
    setMode(null);
    setLocating(!browsing);
  }

  useEscape(true, onClose);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
    return () => {
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    let live = true;
    cached(infoCache, target.docId, () => api.getDocumentInfo(target.docId))
      .then((i) => live && setInfo(i))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [target.docId]);

  // Locate the passage for every new citation, then flash it.
  useEffect(() => {
    if (browsing) return;
    const controller = new AbortController();
    api
      .locate(
        docId,
        {
          page: targetPage ?? undefined,
          chunk_id: chunkId || undefined,
          claim: claim || undefined,
          passage: chunkId ? undefined : passage,
          table: table || undefined,
          exact: exact || undefined,
        },
        controller.signal,
      )
      .then((r) => setLoc(r))
      .catch(() => {
        if (!controller.signal.aborted) setLoc({ page: targetPage ?? 1, rects: [], quote: '', method: 'page' });
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setLocating(false);
        setFlash((f) => f + 1);
      });
    return () => controller.abort();
  }, [shownKey, browsing, docId, targetPage, chunkId, claim, passage, table, exact]);

  /** Shows a quoted value from the Details tab in the document (exact quote, flashed). */
  const showQuote = useCallback(
    (page: number | null, quoteChunk: string | null, quote: string) => {
      setTab('document');
      api
        .locate(docId, { page: page ?? undefined, chunk_id: quoteChunk || undefined, claim: quote, exact: true })
        .then((r) => {
          setLoc(r);
          setFlash((f) => f + 1);
        })
        .catch(() => undefined);
    },
    [docId],
  );

  /** Flashes a sensitive value found by the Privacy tab (boxes are known; no lookup needed). */
  const showFinding = useCallback((f: SensitiveFinding) => {
    setTab('document');
    setLoc({ page: f.page, rects: f.rects, quote: '', method: f.rects.length ? 'sentence' : 'text', chunk_id: f.chunk_id || undefined });
    setFlash((n) => n + 1);
  }, []);

  const jumpToPage = useCallback((page: number) => {
    setTab('document');
    setLoc({ page, rects: [], quote: '', method: 'page' });
    setFlash((f) => f + 1);
  }, []);

  const spreadsheet = !!info && SPREADSHEETS.has(info.file_type) && info.tables.length > 0;
  const view: 'pages' | 'table' | 'text' | null = !info
    ? null
    : info.viewer === 'pages'
      ? 'pages'
      : (mode ?? (spreadsheet && (target.table || !target.chunkId) ? 'table' : 'text'));
  const tableName = target.table || info?.tables[0]?.table;
  const page = loc?.page ?? target.page ?? null;
  const pageInfo = info && page ? info.pages[page - 1] : undefined;
  const title = info?.filename || target.docTitle || 'Document';

  let status = 'Finding the passage…';
  if (browsing && !loc) {
    const parts = info?.pages.length ? [pluralize(info.pages.length, 'page')] : [];
    if (info?.ocr_pages.length) parts.push(`${info.ocr_pages.length} read with OCR`);
    if (info?.tables.length) parts.push(pluralize(info.tables.length, 'table'));
    status = info ? parts.join(' · ') || (info.file_type || '').toUpperCase() : 'Opening…';
  } else if (!locating && loc) {
    if (loc.method === 'sentence') status = target.exact ? 'Quoted text highlighted' : 'Supporting sentence highlighted';
    else if (loc.method === 'passage') status = 'Cited passage highlighted';
    else if (loc.method === 'table') status = 'Cited table highlighted';
    else if (loc.method === 'text') status = loc.quote ? 'Supporting sentence highlighted' : 'Cited passage highlighted';
    else status = target.chunkId || target.claim ? 'Cited page (the exact passage could not be located)' : `Page ${loc.page ?? 1}`;
  }
  if (view === 'table') status = target.sql ? 'Figures computed from this table' : 'Table extracted from the document';

  return (
    <aside className={styles.panel} aria-labelledby="viewer-title">
      <header className={styles.head}>
        <div className={styles.heading}>
          <span className={styles.kind}>
            {target.label || 'Source'}
            {page != null && view !== 'table' && <> · p. {page}</>}
          </span>
          <h2 id="viewer-title" className={styles.title} title={title}>
            {title}
          </h2>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" aria-label="Close document" title="Close (Esc)" onClick={onClose}>
          <X size={18} strokeWidth={1.75} />
        </button>
      </header>

      <div className={styles.toolbar}>
        <div className={styles.tabs} role="tablist" aria-label="Document views">
          <button type="button" role="tab" aria-selected={tab === 'document'} className={styles.tab} onClick={() => setTab('document')}>
            Document
          </button>
          <button type="button" role="tab" aria-selected={tab === 'summary'} className={styles.tab} onClick={() => setTab('summary')}>
            Summary
          </button>
          <button type="button" role="tab" aria-selected={tab === 'details'} className={styles.tab} onClick={() => setTab('details')}>
            Details
          </button>
          <button type="button" role="tab" aria-selected={tab === 'privacy'} className={styles.tab} onClick={() => setTab('privacy')}>
            Privacy
          </button>
        </div>
        <div className={styles.tools}>
          {tab === 'document' && spreadsheet && (
            <div className={styles.segmented} role="group" aria-label="Show as">
              <button type="button" aria-pressed={view === 'table'} onClick={() => setMode('table')}>
                Table
              </button>
              <button type="button" aria-pressed={view === 'text'} onClick={() => setMode('text')}>
                Text
              </button>
            </div>
          )}
          {tab === 'document' && view === 'pages' && (
            <div className={styles.zoom} role="group" aria-label="Zoom">
              <button
                type="button"
                className="icon-btn icon-btn-sm"
                aria-label="Zoom out"
                disabled={zoom <= ZOOMS[0]}
                onClick={() => setZoom((z) => ZOOMS[Math.max(0, ZOOMS.indexOf(z) - 1)])}
              >
                <Minus size={14} strokeWidth={2} />
              </button>
              <span className="num">{Math.round(zoom * 100)}%</span>
              <button
                type="button"
                className="icon-btn icon-btn-sm"
                aria-label="Zoom in"
                disabled={zoom >= ZOOMS[ZOOMS.length - 1]}
                onClick={() => setZoom((z) => ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(z) + 1)])}
              >
                <Plus size={14} strokeWidth={2} />
              </button>
            </div>
          )}
          {tab === 'document' && !(browsing && !loc) && (
            <button
              type="button"
              className="icon-btn icon-btn-sm"
              aria-label="Highlight again"
              title="Highlight again"
              disabled={locating}
              onClick={() => setFlash((f) => f + 1)}
            >
              <Highlighter size={15} strokeWidth={1.75} />
            </button>
          )}
          <a
            className="icon-btn icon-btn-sm"
            href={api.documentFileUrl(target.docId, info?.file_type === 'pdf' ? page : null)}
            target="_blank"
            rel="noreferrer noopener"
            aria-label="Open the original file"
            title="Open the original file"
          >
            <ExternalLink size={15} strokeWidth={1.75} />
          </a>
        </div>
      </div>

      {tab === 'document' && (
        <div className={styles.status} aria-live="polite">
          <span className={styles.statusDot} data-state={locating ? 'busy' : loc?.rects.length || loc?.quote ? 'found' : 'page'} aria-hidden="true" />
          <span>{status}</span>
          {pageInfo?.ocr && (
            <span className={styles.ocrNote} title="This page is a scan; its text was read with OCR">
              <ScanText size={13} strokeWidth={1.75} /> OCR{pageInfo.lang ? ` · ${languageLabel(pageInfo.lang)}` : ''}
            </span>
          )}
        </div>
      )}
      {tab === 'document' && target.sql && (
        <details className={styles.sql}>
          <summary>SQL used for the answer</summary>
          <pre>{target.sql}</pre>
        </details>
      )}

      <div className={styles.body}>
        {error ? (
          <div className={styles.message} role="alert">
            {error}
          </div>
        ) : tab === 'privacy' ? (
          <PrivacyView docId={target.docId} onShow={showFinding} />
        ) : tab === 'details' ? (
          <DetailsView docId={target.docId} onShow={showQuote} />
        ) : tab === 'summary' ? (
          <SummaryView docId={target.docId} onJump={jumpToPage} />
        ) : !info ? (
          <div className={styles.loading} aria-hidden="true">
            <span />
          </div>
        ) : view === 'pages' ? (
          <PageView docId={target.docId} info={info} loc={loc} flash={flash} zoom={zoom} />
        ) : view === 'table' && tableName ? (
          <TableView key={tableName} docId={target.docId} info={info} initialTable={tableName} flash={flash} />
        ) : (
          <TextView docId={target.docId} loc={loc} chunkId={loc?.chunk_id || target.chunkId} flash={flash} info={info} />
        )}
      </div>
    </aside>
  );
}

/* --------------------------------------------------------------- page view */

function PageView({ docId, info, loc, flash, zoom }: { docId: string; info: DocumentInfo; loc: LocateResult | null; flash: number; zoom: number }) {
  const [scrollRef, size] = useElementSize<HTMLDivElement>();
  const pageRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [current, setCurrent] = useState(loc?.page ?? 1);
  const frame = useRef(0);
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
  const needed = Math.max(320, size.width - 32) * zoom * dpr;
  const imgWidth = PAGE_WIDTHS.find((w) => w >= needed) ?? PAGE_WIDTHS[PAGE_WIDTHS.length - 1];
  const count = info.pages.length;

  // Bring the highlight into view for every new location (and on "highlight again").
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !loc || !flash) return;
    const pageEl = pageRefs.current[(loc.page ?? 1) - 1];
    if (!pageEl) return;
    const rects = loc.rects as Rect[];
    const top = rects.length ? Math.min(...rects.map((r) => r[1])) : 0;
    const left = rects.length ? Math.min(...rects.map((r) => r[0])) : 0;
    const y = pageEl.offsetTop + top * pageEl.clientHeight - (rects.length ? el.clientHeight * 0.3 : 12);
    const x = zoom > 1 ? pageEl.offsetLeft + left * pageEl.clientWidth - 24 : 0;
    const far = Math.abs(el.scrollTop - y) > el.clientHeight * 3;
    el.scrollTo({ top: Math.max(0, y), left: Math.max(0, x), behavior: far ? 'auto' : 'smooth' });
  }, [flash, loc, zoom, scrollRef]);

  const onScroll = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (!el) return;
      const middle = el.scrollTop + el.clientHeight / 2;
      let n = 1;
      pageRefs.current.forEach((p, i) => {
        if (p && p.offsetTop <= middle) n = i + 1;
      });
      setCurrent(n);
    });
  };
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const goTo = (n: number) => {
    const el = scrollRef.current;
    const pageEl = pageRefs.current[n - 1];
    if (el && pageEl) el.scrollTo({ top: pageEl.offsetTop - 12, behavior: 'smooth' });
  };

  return (
    <div className={styles.pageViewer}>
      <div className={styles.pages} ref={scrollRef} onScroll={onScroll} tabIndex={0} aria-label="Document pages">
        <div className={styles.pageColumn} style={{ width: `${zoom * 100}%` }}>
          {info.pages.map((p, i) => {
            const n = i + 1;
            const here = loc && loc.page === n;
            const rects = here ? (loc.rects as Rect[]) : [];
            return (
              <div
                key={n}
                ref={(el) => {
                  pageRefs.current[i] = el;
                }}
                className={styles.page}
                style={{ aspectRatio: `${p.w || 612} / ${p.h || 792}` }}
              >
                <img
                  src={api.pageImageUrl(docId, n, imgWidth)}
                  alt={`Page ${n}`}
                  loading={Math.abs(n - (loc?.page ?? 1)) <= 1 ? 'eager' : 'lazy'}
                  decoding="async"
                  draggable={false}
                />
                {flash > 0 &&
                  rects.map((r, j) => <span key={`${flash}-${j}`} className={styles.mark} style={rectStyle(r)} aria-hidden="true" />)}
                {flash > 0 && rects.length > 0 && <span key={`bar-${flash}`} className={styles.marginMark} style={marginStyle(rects)} aria-hidden="true" />}
                {flash > 0 && here && !rects.length && <span key={`page-${flash}`} className={styles.pageFlash} aria-hidden="true" />}
              </div>
            );
          })}
        </div>
      </div>
      {count > 1 && (
        <div className={styles.pager}>
          <button type="button" aria-label="Previous page" disabled={current <= 1} onClick={() => goTo(current - 1)}>
            <ChevronUp size={15} strokeWidth={2} />
          </button>
          <span className="num" aria-live="polite">
            {current} / {count}
          </span>
          <button type="button" aria-label="Next page" disabled={current >= count} onClick={() => goTo(current + 1)}>
            <ChevronDown size={15} strokeWidth={2} />
          </button>
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- text view */

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${String(m).padStart(2, '0')}:${sec}`;
}

/** Player for a recording: the cited passage's start is one click away. */
function MediaPlayer({ docId, media, start }: { docId: string; media: NonNullable<DocumentInfo['media']>; start: number | null }) {
  const ref = useRef<HTMLMediaElement | null>(null);
  useEffect(() => {
    if (ref.current && start != null) ref.current.currentTime = start;
  }, [start]);
  const src = api.documentFileUrl(docId);
  const play = () => {
    if (!ref.current) return;
    if (start != null) ref.current.currentTime = start;
    ref.current.play().catch(() => undefined);
  };
  return (
    <div className={styles.media}>
      {media.kind === 'video' ? (
        <video ref={(el) => { ref.current = el; }} src={src} controls preload="metadata" className={styles.video} />
      ) : (
        <audio ref={(el) => { ref.current = el; }} src={src} controls preload="metadata" className={styles.audio} />
      )}
      <div className={styles.mediaMeta}>
        {start != null && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={play}>
            Play from {clock(start)}
          </button>
        )}
        <span>{media.engine ? `Transcribed with ${media.engine}` : 'Transcript'}{media.language ? ` · ${media.language}` : ''}</span>
      </div>
    </div>
  );
}

function TextView({ docId, loc, chunkId, flash, info }: { docId: string; loc: LocateResult | null; chunkId?: string; flash: number; info?: DocumentInfo | null }) {
  const [doc, setDoc] = useState<DocumentText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const media = info?.media ?? null;
  const mediaStart = media && chunkId ? media.chunk_starts?.[chunkId] ?? null : null;

  useEffect(() => {
    let live = true;
    cached(textCache, docId, () => api.getDocumentText(docId))
      .then((d) => live && setDoc(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [docId]);

  const cited = doc?.chunks.find((c) => c.chunk_id === chunkId);
  const range = cited ? findQuote(cited.text, loc?.quote) : null;
  const paged = !!doc && new Set(doc.chunks.map((c) => c.page)).size > 1;

  useEffect(() => {
    if (!doc || !flash) return;
    const root = scrollRef.current;
    const el =
      root?.querySelector<HTMLElement>('[data-quote="true"]') ||
      root?.querySelector<HTMLElement>('[data-cited="true"]') ||
      (loc?.page ? root?.querySelector<HTMLElement>(`[data-page="${loc.page}"]`) : null);
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [doc, flash, loc]);

  if (error) return <div className={styles.message} role="alert">{error}</div>;
  if (!doc)
    return (
      <div className={styles.loading} aria-hidden="true">
        <span />
      </div>
    );
  if (!doc.chunks.length) return <div className={styles.message}>This document has no readable text.</div>;

  return (
    <div className={styles.textScroll} ref={scrollRef} tabIndex={0} aria-label="Document text">
      {media && <MediaPlayer docId={docId} media={media} start={mediaStart} />}
      <article className={styles.reader}>
        {info?.attachments && info.attachments.length > 0 && (
          <p className={styles.attachments}>Attachments: {info.attachments.join(', ')}</p>
        )}
        {doc.chunks.map((c, i) => {
          const prev = doc.chunks[i - 1];
          const newPage = paged && (!prev || prev.page !== c.page);
          const newSection = c.section && c.section !== 'General' && (!prev || prev.section !== c.section);
          const isCited = c.chunk_id === chunkId;
          return (
            <Fragment key={c.chunk_id}>
              {newPage && (
                <div className={styles.pageRule} data-page={c.page}>
                  <span>Page {c.page}</span>
                </div>
              )}
              {newSection && <h3 className={styles.readerHeading}>{c.section}</h3>}
              <p key={isCited ? `cited-${flash}` : c.chunk_id} className={styles.passage} data-cited={isCited || undefined}>
                {isCited && range ? (
                  <>
                    {c.text.slice(0, range[0])}
                    <mark key={`q-${flash}`} className={styles.quote} data-quote="true">
                      {c.text.slice(range[0], range[1])}
                    </mark>
                    {c.text.slice(range[1])}
                  </>
                ) : (
                  c.text
                )}
              </p>
            </Fragment>
          );
        })}
      </article>
    </div>
  );
}

/* -------------------------------------------------------------- table view */

function TableView({ docId, info, initialTable, flash }: { docId: string; info: DocumentInfo; initialTable: string; flash: number }) {
  const [name, setName] = useState(initialTable);
  const [loaded, setLoaded] = useState<TableData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const data = loaded && loaded.table === name ? loaded : null;

  useEffect(() => {
    let live = true;
    api
      .getDocumentTable(docId, name)
      .then((d) => live && setLoaded(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [docId, name]);

  return (
    <div className={styles.tableViewer}>
      {info.tables.length > 1 && (
        <label className={styles.tablePick}>
          <span>Table</span>
          <select className="field" value={name} onChange={(e) => setName(e.target.value)}>
            {info.tables.map((t) => (
              <option key={t.table} value={t.table}>
                {t.title || t.table}
                {t.page ? ` (p. ${t.page})` : ''}
              </option>
            ))}
          </select>
        </label>
      )}
      {error ? (
        <div className={styles.message} role="alert">{error}</div>
      ) : !data ? (
        <div className={styles.loading} aria-hidden="true">
          <span />
        </div>
      ) : (
        <>
          <div className={styles.tableMeta}>
            <strong>{data.title || data.table}</strong>
            <span>
              {pluralize(data.n_rows, 'row')} · {pluralize(data.columns.length, 'column')}
              {data.truncated ? ` · first ${data.rows.length} shown` : ''}
            </span>
          </div>
          <div key={`t-${flash}`} className={styles.gridWrap} data-flash={flash > 0 || undefined}>
            <table className={styles.grid}>
              <thead>
                <tr>
                  {data.columns.map((c, i) => (
                    <th key={i}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, ri) => (
                  <tr key={ri}>
                    {r.map((v, ci) => (
                      <td key={ci} data-num={typeof v === 'number' || undefined}>
                        {v == null ? '' : typeof v === 'number' ? v.toLocaleString() : v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ summary view */

function SummaryView({ docId, onJump }: { docId: string; onJump: (page: number) => void }) {
  const [state, setState] = useState<{ status: 'ready' | 'pending' | 'missing'; summary: DocumentSummary | null; progress?: { processed: number; total: number } | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(() => {
    api
      .getDocumentSummary(docId)
      .then(setState)
      .catch((e: Error) => setError(e.message));
  }, [docId]);

  useEffect(load, [load]);
  useEffect(() => {
    if (state?.status !== 'pending') return;
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, [state?.status, load]);

  const sectionPage = useMemo(() => {
    const m = new Map<number, number>();
    state?.summary?.sections.forEach((s) => m.set(s.i, s.pages[0]));
    return m;
  }, [state?.summary]);

  if (error) return <div className={styles.message} role="alert">{error}</div>;
  if (!state)
    return (
      <div className={styles.loading} aria-hidden="true">
        <span />
      </div>
    );
  if (state.status !== 'ready' || !state.summary) {
    const p = state.progress;
    return (
      <div className={styles.summaryEmpty}>
        {state.status === 'pending' ? (
          <>
            <span className="spinner" />
            <p>
              Summarizing this document
              {p && p.total ? ` (${p.processed} of ${p.total} steps)` : ''}…
            </p>
          </>
        ) : (
          <>
            <p>This document has no summary yet. Summaries let OmniDoc answer questions about whole documents and your whole library.</p>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={starting}
              onClick={async () => {
                setStarting(true);
                try {
                  await api.summarizeMissing([docId]);
                  load();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setStarting(false);
                }
              }}
            >
              {starting && <span className="spinner" />} Write a summary
            </button>
          </>
        )}
      </div>
    );
  }

  const s = state.summary;
  return (
    <div className={styles.textScroll}>
      <article className={styles.summary}>
        <p className={styles.overview}>{s.summary}</p>
        {s.key_points.length > 0 && (
          <>
            <h3 className={styles.summaryHeading}>Key points</h3>
            <ul className={styles.points}>
              {s.key_points.map((k, i) => (
                <li key={i}>
                  <span>{k.text}</span>
                  {k.sections.map((n) =>
                    sectionPage.has(n) ? (
                      <button key={n} type="button" className={styles.pageLink} onClick={() => onJump(sectionPage.get(n)!)}>
                        p. {sectionPage.get(n)}
                      </button>
                    ) : null,
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
        {s.topics.length > 0 && (
          <div className={styles.topics}>
            {s.topics.map((t) => (
              <span key={t} className={styles.topic}>
                {t}
              </span>
            ))}
          </div>
        )}
        {s.sections.length > 1 && (
          <>
            <h3 className={styles.summaryHeading}>By section</h3>
            <ol className={styles.sections}>
              {s.sections.map((sec) => (
                <li key={sec.i}>
                  <button type="button" className={styles.sectionHead} onClick={() => onJump(sec.pages[0])}>
                    <span>{sec.title}</span>
                    <span className="num">
                      {sec.pages[0] === sec.pages[1] ? `p. ${sec.pages[0]}` : `pp. ${sec.pages[0]}–${sec.pages[1]}`}
                    </span>
                  </button>
                  <p>{sec.summary}</p>
                </li>
              ))}
            </ol>
          </>
        )}
      </article>
    </div>
  );
}

/* ------------------------------------------------------------ details view */

const TYPE_CHOICES: Array<[string, string]> = [
  ['invoice', 'Invoice'], ['receipt', 'Receipt'], ['purchase_order', 'Purchase order'], ['contract', 'Contract'],
  ['resume', 'Resume'], ['research_paper', 'Research paper'], ['report', 'Report'], ['bank_statement', 'Bank statement'],
];

function formatField(v: unknown): string {
  if (v == null) return '';
  if (Array.isArray(v)) return v.join('; ');
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 6 });
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

/** The document's detected type, the fields extracted for it and their consistency checks. */
function DetailsView({ docId, onShow }: { docId: string; onShow: (page: number | null, chunk: string | null, quote: string) => void }) {
  const [rec, setRec] = useState<DocumentRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [type, setType] = useState('');

  const load = useCallback(() => {
    api
      .getRecord(docId)
      .then((r) => {
        setRec(r);
        setType(r.doc_type);
      })
      .catch((e: Error) => setError(e.message));
  }, [docId]);
  useEffect(load, [load]);
  useEffect(() => {
    if (!rec?.pending) return;
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, [rec?.pending, load]);

  const extract = async () => {
    setBusy(true);
    setError(null);
    try {
      setRec(await api.extractRecord(docId, type !== rec?.doc_type ? type : undefined));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!rec && !error)
    return (
      <div className={styles.loading} aria-hidden="true">
        <span />
      </div>
    );
  const fields = rec?.record?.fields ?? [];
  const checks = (rec?.record?.validation ?? []).filter((c) => c.status !== 'skip');
  return (
    <div className={styles.textScroll}>
      <div className={styles.details}>
        <div className={styles.detailsHead}>
          <span className={styles.typeBadge}>{rec?.label ?? 'Document'}</span>
          {rec?.confidence != null && rec.confidence > 0 && <span className={styles.stepMeta}>detected · {Math.round(rec.confidence * 100)}%</span>}
          <span className={styles.grow} />
          <select className="field" value={type} onChange={(e) => setType(e.target.value)} aria-label="Document type">
            {!TYPE_CHOICES.some(([k]) => k === type) && <option value={type}>{rec?.label ?? type}</option>}
            {TYPE_CHOICES.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy || rec?.pending || !TYPE_CHOICES.some(([k]) => k === type)} onClick={extract}>
            {busy || rec?.pending ? <span className="spinner" /> : <RefreshCw size={13} strokeWidth={2} />}
            {rec?.record ? 'Extract again' : 'Extract fields'}
          </button>
        </div>
        {error && <p className={styles.message} role="alert">{error}</p>}
        {rec?.pending && <p className={styles.summaryNote}>Extracting the fields of this document…</p>}
        {!rec?.record && !rec?.pending && (
          <p className={styles.summaryNote}>
            {TYPE_CHOICES.some(([k]) => k === rec?.doc_type)
              ? 'Fields have not been extracted yet.'
              : 'No extraction template fits this document. Pick a type to extract its fields.'}
          </p>
        )}
        {checks.length > 0 && (
          <ul className={styles.checks}>
            {checks.map((c, i) => (
              <li key={i} data-status={c.status}>
                {c.status === 'ok' ? <Check size={14} strokeWidth={2.2} /> : <AlertTriangle size={14} strokeWidth={2} />}
                <span>
                  <strong>{c.rule}</strong> {c.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        {fields.length > 0 && (
          <dl className={styles.fieldList}>
            {fields.map((f) => (
              <div key={f.name} data-status={f.status}>
                <dt>{f.label}</dt>
                <dd>
                  {f.value == null ? <span className={styles.none}>Not found</span> : <span>{formatField(f.value)}</span>}
                  {f.status === 'check' && <AlertTriangle size={13} strokeWidth={2} aria-label="Check this value" />}
                  {f.status === 'missing' && <CircleDashed size={13} strokeWidth={2} aria-hidden="true" />}
                  {f.quote && f.page != null && (
                    <button type="button" className={styles.pageLink} onClick={() => onShow(f.page, f.chunk_id, f.quote || '')}>
                      p. {f.page}
                    </button>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- web view */

/** A cited web page, read on the server and shown as clean paragraphs with the cited passage flashed. */
function WebPanel({ target, onClose }: { target: ViewerTarget; onClose: () => void }) {
  const [page, setPage] = useState<WebPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const { url = '', passage = '', claim = '' } = target;

  useEscape(true, onClose);
  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api
      .webPage(url, passage, claim, controller.signal)
      .then((p) => {
        setPage(p);
        setFlash((f) => f + 1);
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [url, passage, claim, target.key]);

  useEffect(() => {
    if (!page || !flash) return;
    const el = scrollRef.current?.querySelector<HTMLElement>('[data-quote="true"]') ||
      scrollRef.current?.querySelector<HTMLElement>('[data-cited="true"]');
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [page, flash]);

  const cited = page?.highlight.paragraph ?? null;
  const site = page?.site || (() => {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  })();
  const status = !page && !error ? 'Reading the page…' : cited == null ? 'Page opened (the cited passage was not found on it now)'
    : page?.highlight.quote ? 'Supporting sentence highlighted' : 'Cited passage highlighted';

  return (
    <aside className={styles.panel} aria-labelledby="web-title">
      <header className={styles.head}>
        <div className={styles.heading}>
          <span className={styles.kind}>{target.label || 'Web source'}</span>
          <h2 id="web-title" className={styles.title} title={page?.title || target.docTitle}>
            {page?.title || target.docTitle || site}
          </h2>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" aria-label="Close page" title="Close (Esc)" onClick={onClose}>
          <X size={18} strokeWidth={1.75} />
        </button>
      </header>
      <div className={styles.toolbar}>
        <div className={styles.siteLine}>
          <Globe2 size={14} strokeWidth={1.75} /> {site}
          {page?.published ? ` · ${page.published.slice(0, 10)}` : ''}
        </div>
        <div className={styles.tools}>
          <button type="button" className="icon-btn icon-btn-sm" aria-label="Highlight again" title="Highlight again" disabled={!page} onClick={() => setFlash((f) => f + 1)}>
            <Highlighter size={15} strokeWidth={1.75} />
          </button>
          <a className="icon-btn icon-btn-sm" href={url} target="_blank" rel="noreferrer noopener" aria-label="Open on the site" title="Open on the site">
            <ExternalLink size={15} strokeWidth={1.75} />
          </a>
        </div>
      </div>
      <div className={styles.status} aria-live="polite">
        <span className={styles.statusDot} data-state={!page && !error ? 'busy' : cited != null ? 'found' : 'page'} aria-hidden="true" />
        <span>{error || status}</span>
      </div>
      <div className={styles.body}>
        {error ? (
          <div className={styles.message} role="alert">
            {error} <a href={url} target="_blank" rel="noreferrer noopener">Open it on the site</a>.
          </div>
        ) : !page ? (
          <div className={styles.loading} aria-hidden="true">
            <span />
          </div>
        ) : (
          <div className={styles.textScroll} ref={scrollRef} tabIndex={0} aria-label="Page text">
            <article className={styles.reader}>
              {page.paragraphs.map((p, i) => {
                if (p.startsWith('## ')) return <h3 key={i} className={styles.readerHeading}>{p.slice(3)}</h3>;
                const isCited = i === cited;
                const range = isCited ? findQuote(p, page.highlight.quote) : null;
                return (
                  <p key={isCited ? `cited-${flash}` : i} className={styles.passage} data-cited={isCited || undefined}>
                    {range ? (
                      <>
                        {p.slice(0, range[0])}
                        <mark key={`q-${flash}`} className={styles.quote} data-quote="true">
                          {p.slice(range[0], range[1])}
                        </mark>
                        {p.slice(range[1])}
                      </>
                    ) : (
                      p
                    )}
                  </p>
                );
              })}
            </article>
          </div>
        )}
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------ privacy view */

/** Personal and financial identifiers in the document (masked), each one shown on the page, and a redacted copy. */
function PrivacyView({ docId, onShow }: { docId: string; onShow: (f: SensitiveFinding) => void }) {
  const [data, setData] = useState<{ findings: SensitiveFinding[]; counts: Record<string, number> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [skip, setSkip] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getSensitive(docId)
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [docId]);

  const types = useMemo(() => {
    const seen = new Map<string, string>();
    data?.findings.forEach((f) => seen.set(f.type, f.label));
    return [...seen.entries()];
  }, [data]);

  const download = async () => {
    setBusy(true);
    try {
      const { blob, filename } = await api.redact(docId, types.map(([t]) => t).filter((t) => !skip.includes(t)));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className={styles.message} role="alert">{error}</div>;
  if (!data)
    return (
      <div className={styles.loading} aria-hidden="true">
        <span />
      </div>
    );
  return (
    <div className={styles.textScroll}>
      <div className={styles.details}>
        {data.findings.length === 0 ? (
          <p className={styles.summaryNote}>No personal or financial identifiers were found (Aadhaar, PAN, GSTIN, IFSC, card, account and passport numbers, phone numbers, e-mail addresses, dates of birth).</p>
        ) : (
          <>
            <p className={styles.summaryNote}>
              {data.findings.length} sensitive value{data.findings.length === 1 ? '' : 's'} found. Values are masked here; select one to see it on the page.
            </p>
            <div className={styles.typeFilters}>
              {types.map(([t, label]) => (
                <label key={t} className={styles.typeFilter}>
                  <input type="checkbox" checked={!skip.includes(t)} onChange={() => setSkip((s) => (s.includes(t) ? s.filter((x) => x !== t) : [...s, t]))} />
                  {label} <span className="num">{data.counts[label]}</span>
                </label>
              ))}
            </div>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || types.every(([t]) => skip.includes(t))} onClick={download}>
              {busy && <span className="spinner" />} Download redacted copy
            </button>
            <ul className={styles.findings}>
              {data.findings.map((f, i) => (
                <li key={i}>
                  <button type="button" onClick={() => onShow(f)}>
                    <span className={styles.findingLabel}>{f.label}</span>
                    <span className="num">{f.masked}</span>
                    <span className={styles.findingPage}>p. {f.page}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
