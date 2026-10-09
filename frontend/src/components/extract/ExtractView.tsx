import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Download,
  ListChecks,
  Minus,
  PanelLeftOpen,
  Plus,
  ScanSearch,
  Square,
  Trash2,
  Upload,
} from 'lucide-react';
import { api } from '../../api';
import type { DocumentItem, ExtractField, ExtractFieldResult, ExtractPreset, ExtractResult, FieldType } from '../../api';
import { pluralize } from '../../lib/format';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import styles from './ExtractView.module.css';

interface ExtractViewProps {
  documents: DocumentItem[];
  /** Documents selected elsewhere (the chat scope), preselected here */
  selectedDocIds: string[];
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onOpenLibrary: () => void;
}

interface FieldDraft extends ExtractField {
  id: number;
}

const TYPE_LABELS: Record<FieldType, string> = { text: 'Text', number: 'Number', date: 'Date', list: 'List', boolean: 'Yes / no' };
const STATUS_LABELS: Record<ExtractFieldResult['status'], string> = { found: 'Quoted', check: 'Check', missing: 'Not found' };

let nextId = 1;
let opened = 0;
const draft = (f: Partial<ExtractField> = {}): FieldDraft => ({
  id: nextId++,
  name: f.name ?? '',
  label: f.label ?? '',
  description: f.description ?? '',
  type: f.type ?? 'text',
});

function formatValue(v: ExtractFieldResult['value']): string {
  if (v == null) return '';
  if (Array.isArray(v)) return v.join('; ');
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 6 });
  return String(v);
}

function csvText(rows: string[][]): string {
  const cell = (c: string) => (/[",\n\r]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c);
  return rows.map((r) => r.map((c) => cell(String(c ?? ''))).join(',')).join('\r\n');
}

function download(name: string, type: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function ExtractView({ documents, selectedDocIds, sidebarOpen, onOpenSidebar, onOpenLibrary }: ExtractViewProps) {
  const [presets, setPresets] = useState<ExtractPreset[]>([]);
  const [types, setTypes] = useState<FieldType[]>(['text', 'number', 'date', 'list', 'boolean']);
  const [preset, setPreset] = useState<string>('custom');
  const [fields, setFields] = useState<FieldDraft[]>([draft()]);
  const [docIds, setDocIds] = useState<string[]>(() => selectedDocIds.filter((id) => documents.some((d) => d.id === id)));
  const [filter, setFilter] = useState('');
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ title: string; index: number; total: number; done: number; batches: number } | null>(null);
  const [results, setResults] = useState<ExtractResult[]>([]);
  const [failures, setFailures] = useState<Array<{ doc_id: string; title: string; message: string }>>([]);
  const [csv, setCsv] = useState<string[][]>([]);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api
      .getExtractPresets()
      .then((p) => {
        setPresets(p.presets);
        if (p.types?.length) setTypes(p.types);
      })
      .catch((e: Error) => setError(e.message));
    return () => controllerRef.current?.abort();
  }, []);

  const shownDocs = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? documents.filter((d) => d.filename.toLowerCase().includes(q)) : documents;
  }, [documents, filter]);

  const validFields = fields.filter((f) => f.label.trim());
  const liveDocIds = docIds.filter((id) => documents.some((d) => d.id === id));
  const canRun = !running && validFields.length > 0 && liveDocIds.length > 0;

  const choosePreset = (key: string) => {
    setPreset(key);
    const p = presets.find((x) => x.key === key);
    setFields(p ? p.fields.map((f) => draft(f)) : [draft()]);
  };

  const updateField = (id: number, patch: Partial<ExtractField>) => {
    setPreset('custom');
    setFields((fs) => fs.map((f) => (f.id === id ? { ...f, ...patch, ...(patch.label != null ? { name: '' } : {}) } : f)));
  };

  const run = async () => {
    if (!canRun) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setRunning(true);
    setError(null);
    setResults([]);
    setFailures([]);
    setCsv([]);
    setViewer(null);
    try {
      const rows = await api.streamExtract(
        {
          document_ids: liveDocIds,
          fields: validFields.map(({ name, label, description, type }) => ({ name: name || label, label, description, type })),
        },
        {
          signal: controller.signal,
          onDocStart: (d) => setProgress({ title: d.title, index: d.index, total: d.total, done: 0, batches: 0 }),
          onProgress: (p) => setProgress((cur) => (cur ? { ...cur, done: p.done, batches: p.total } : cur)),
          onResult: (r) => setResults((rs) => [...rs, r]),
          onDocError: (e) => setFailures((fs) => [...fs, e]),
        },
      );
      setCsv(rows);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      setRunning(false);
      setProgress(null);
      controllerRef.current = null;
    }
  };

  const openField = (r: ExtractResult, f: ExtractFieldResult) =>
    setViewer({
      key: `${r.doc_id}-${f.name}-${++opened}`,
      docId: r.doc_id,
      docTitle: r.title,
      page: f.page,
      chunkId: f.chunk_id ?? undefined,
      claim: f.quote ?? formatValue(f.value),
      exact: !!f.quote,
      passage: r.sources.find((s) => s.n === f.source)?.snippet,
      label: f.label,
    });

  const exportJson = () =>
    download(
      'omnidoc-extraction.json',
      'application/json',
      JSON.stringify(
        results.map((r) => ({
          document: r.title,
          doc_id: r.doc_id,
          fields: Object.fromEntries(
            r.fields.map((f) => [f.name, { label: f.label, value: f.value, status: f.status, page: f.page, quote: f.quote, note: f.note || undefined }]),
          ),
        })),
        null,
        2,
      ),
    );

  const found = results.reduce((a, r) => a + r.fields.filter((f) => f.status === 'found').length, 0);
  const total = results.reduce((a, r) => a + r.fields.length, 0);

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
          <div className={styles.titleRow}>
            <h1 className={styles.title}>Extract</h1>
            <p className={styles.subtitle}>
              Fill a set of fields from your documents. Every value comes with the passage it was quoted from, checked against the
              document.
            </p>
          </div>

          {!documents.length ? (
            <div className={styles.empty}>
              <p>Add documents to your library first.</p>
              <button type="button" className="btn btn-primary" onClick={onOpenLibrary}>
                <Upload size={15} strokeWidth={1.75} /> Go to the library
              </button>
            </div>
          ) : (
            <section className={styles.setup} aria-label="Extraction setup">
              <div className={styles.step}>
                <h2 className={styles.stepTitle}>Fields</h2>
                <div className={styles.presets} role="radiogroup" aria-label="Template">
                  {presets.map((p) => (
                    <button key={p.key} type="button" role="radio" aria-checked={preset === p.key} className="chip" title={p.description} onClick={() => choosePreset(p.key)}>
                      {p.label}
                    </button>
                  ))}
                  <button type="button" role="radio" aria-checked={preset === 'custom'} className="chip" onClick={() => choosePreset('custom')}>
                    Custom
                  </button>
                </div>
                <ol className={styles.fields}>
                  {fields.map((f, i) => (
                    <li key={f.id} className={styles.fieldRow}>
                      <input
                        className={`field ${styles.fieldLabel}`}
                        value={f.label}
                        placeholder={i === 0 ? 'Field, e.g. Invoice number' : 'Field name'}
                        aria-label={`Field ${i + 1} name`}
                        maxLength={80}
                        onChange={(e) => updateField(f.id, { label: e.target.value })}
                      />
                      <select
                        className={`field ${styles.fieldType}`}
                        value={f.type}
                        aria-label={`Field ${i + 1} type`}
                        onChange={(e) => updateField(f.id, { type: e.target.value as FieldType })}
                      >
                        {types.map((t) => (
                          <option key={t} value={t}>
                            {TYPE_LABELS[t] ?? t}
                          </option>
                        ))}
                      </select>
                      <input
                        className={`field ${styles.fieldDesc}`}
                        value={f.description}
                        placeholder="What to look for (optional)"
                        aria-label={`Field ${i + 1} description`}
                        maxLength={300}
                        onChange={(e) => updateField(f.id, { description: e.target.value })}
                      />
                      <button
                        type="button"
                        className="icon-btn icon-btn-sm"
                        aria-label={`Remove field ${i + 1}`}
                        title="Remove"
                        disabled={fields.length === 1}
                        onClick={() => {
                          setPreset('custom');
                          setFields((fs) => fs.filter((x) => x.id !== f.id));
                        }}
                      >
                        <Minus size={15} strokeWidth={1.75} />
                      </button>
                    </li>
                  ))}
                </ol>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={fields.length >= 30}
                  onClick={() => {
                    setPreset('custom');
                    setFields((fs) => [...fs, draft()]);
                  }}
                >
                  <Plus size={14} strokeWidth={2} /> Add field
                </button>
              </div>

              <div className={styles.step}>
                <div className={styles.stepHead}>
                  <h2 className={styles.stepTitle}>Documents</h2>
                  <span className={styles.stepMeta}>{liveDocIds.length ? `${liveDocIds.length} selected` : 'None selected'}</span>
                  {documents.length > 1 && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setDocIds(liveDocIds.length === documents.length ? [] : documents.map((d) => d.id))}
                    >
                      {liveDocIds.length === documents.length ? 'Clear' : 'Select all'}
                    </button>
                  )}
                </div>
                {documents.length > 8 && (
                  <input className={`field ${styles.docFilter}`} value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter documents" aria-label="Filter documents" />
                )}
                <ul className={styles.docs}>
                  {shownDocs.map((d) => (
                    <li key={d.id}>
                      <label className={styles.doc}>
                        <input
                          type="checkbox"
                          checked={docIds.includes(d.id)}
                          onChange={() => setDocIds((ids) => (ids.includes(d.id) ? ids.filter((x) => x !== d.id) : [...ids, d.id]))}
                        />
                        <span className={styles.docName} title={d.filename}>
                          {d.filename}
                        </span>
                        <span className={styles.docMeta}>
                          {d.pages ? pluralize(d.pages, 'page') : d.file_type.toUpperCase()}
                          {d.ocr_pages ? ' · OCR' : ''}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>

              <div className={styles.runRow}>
                {running ? (
                  <button type="button" className="btn btn-secondary" onClick={() => controllerRef.current?.abort()}>
                    <Square size={13} strokeWidth={2.2} /> Stop
                  </button>
                ) : (
                  <button type="button" className="btn btn-primary" disabled={!canRun} onClick={run}>
                    <ListChecks size={16} strokeWidth={1.9} />
                    Extract {pluralize(validFields.length, 'field')}
                    {liveDocIds.length ? ` from ${pluralize(liveDocIds.length, 'document')}` : ''}
                  </button>
                )}
                {progress && (
                  <span className={styles.progress} aria-live="polite">
                    <span className="spinner" />
                    <span className="shimmer-text">
                      Reading {progress.title}
                      {progress.total > 1 ? ` (${progress.index} of ${progress.total})` : ''}
                      {progress.batches > 1 ? ` · part ${Math.min(progress.done + 1, progress.batches)} of ${progress.batches}` : ''}
                    </span>
                  </span>
                )}
              </div>
              {error && (
                <div className={styles.error} role="alert">
                  <AlertTriangle size={15} strokeWidth={1.75} /> {error}
                </div>
              )}
            </section>
          )}

          {(results.length > 0 || failures.length > 0) && (
            <section className={styles.results} aria-label="Extracted fields">
              <div className={styles.resultsHead}>
                <h2 className={styles.stepTitle}>Results</h2>
                <span className={styles.stepMeta}>
                  {found} of {total} values quoted from the documents
                </span>
                <span className={styles.grow} />
                <button type="button" className="btn btn-ghost btn-sm" disabled={!csv.length} onClick={() => download('omnidoc-extraction.csv', 'text/csv', csvText(csv))}>
                  <Download size={14} strokeWidth={1.75} /> CSV
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={exportJson}>
                  <Download size={14} strokeWidth={1.75} /> JSON
                </button>
              </div>
              {results.map((r) => (
                <article key={r.doc_id} className={styles.card}>
                  <header className={styles.cardHead}>
                    <h3 className={styles.cardTitle}>{r.title}</h3>
                    <span className={styles.stepMeta}>{(r.elapsed_ms / 1000).toFixed(1)} s</span>
                  </header>
                  <dl className={styles.values}>
                    {r.fields.map((f) => (
                      <div key={f.name} className={styles.value} data-status={f.status}>
                        <dt>{f.label}</dt>
                        <dd>
                          <div className={styles.valueLine}>
                            {f.value == null ? <span className={styles.none}>Not found</span> : <span className={styles.valueText}>{formatValue(f.value)}</span>}
                            <span className={styles.status} data-status={f.status} title={f.note || undefined}>
                              {f.status === 'found' ? <Check size={12} strokeWidth={2.4} /> : f.status === 'check' ? <AlertTriangle size={12} strokeWidth={2} /> : null}
                              {STATUS_LABELS[f.status]}
                            </span>
                            {f.page != null && (
                              <button type="button" className={styles.cite} onClick={() => openField(r, f)} title="Show where this was found">
                                <ScanSearch size={13} strokeWidth={1.9} /> p. {f.page}
                              </button>
                            )}
                          </div>
                          {f.quote && <q className={styles.quote}>{f.quote}</q>}
                          {f.note && f.status !== 'found' && <span className={styles.note}>{f.note}</span>}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </article>
              ))}
              {failures.map((f) => (
                <div key={f.doc_id} className={styles.error} role="alert">
                  <AlertTriangle size={15} strokeWidth={1.75} /> {f.title}: {f.message}
                </div>
              ))}
              {!running && results.length > 0 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setResults([]);
                    setFailures([]);
                    setCsv([]);
                    setViewer(null);
                  }}
                >
                  <Trash2 size={14} strokeWidth={1.75} /> Clear results
                </button>
              )}
            </section>
          )}
        </main>
      </div>
      <SourceViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
