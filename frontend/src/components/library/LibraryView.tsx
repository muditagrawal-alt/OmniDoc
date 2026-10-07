import { useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  FileType2,
  MessageSquarePlus,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import type { DocumentItem } from '../../api';
import { formatBytes, formatDate, pluralize } from '../../lib/format';
import { Dialog } from '../ui/Dialog';
import styles from './LibraryView.module.css';

export interface UploadItem {
  id: string;
  name: string;
  status: 'uploading' | 'done' | 'duplicate' | 'error';
  message?: string;
}

interface LibraryViewProps {
  documents: DocumentItem[];
  loading: boolean;
  error: string | null;
  onReload: () => void;
  onUpload: (files: File[]) => void;
  uploads: UploadItem[];
  onDismissUploads: () => void;
  onDelete: (doc: DocumentItem) => Promise<void>;
  selectedDocIds: string[];
  onToggleDoc: (id: string) => void;
  onSetSelection: (ids: string[]) => void;
  onAskSelected: () => void;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
}

const ACCEPT = '.pdf,.docx,.txt,.md';

function GraphStatus({ doc }: { doc: DocumentItem }) {
  const g = doc.graph_status;
  if (!g) return <span className={styles.muted}>—</span>;
  if (g.status === 'done') {
    if (g.entities === 0) return <span className={styles.muted}>No entities</span>;
    return (
      <span className={styles.statusReady} title="Entities extracted into the knowledge graph">
        {g.entities != null ? `${g.entities.toLocaleString()} entities` : 'Mapped'}
      </span>
    );
  }
  if (g.status === 'failed') return <span className={styles.statusBad}>Failed</span>;
  if (g.status === 'cancelled') return <span className={styles.muted}>Stopped</span>;
  const pct = g.total ? Math.round((g.processed / g.total) * 100) : 0;
  return (
    <span className={styles.progress} title={`Extracting entities: ${g.processed} of ${g.total} sections`}>
      <span className={styles.progressBar}>
        <span style={{ width: `${pct}%` }} />
      </span>
      <span className="num">{g.processed}/{g.total}</span>
    </span>
  );
}

export function LibraryView(props: LibraryViewProps) {
  const {
    documents,
    loading,
    error,
    onReload,
    onUpload,
    uploads,
    onDismissUploads,
    onDelete,
    selectedDocIds,
    onToggleDoc,
    onSetSelection,
    onAskSelected,
    sidebarOpen,
    onOpenSidebar,
  } = props;
  const [query, setQuery] = useState('');
  const [dragging, setDragging] = useState(false);
  const [confirm, setConfirm] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? documents.filter((d) => d.filename.toLowerCase().includes(q)) : documents;
  }, [documents, query]);

  const totalBytes = documents.reduce((a, d) => a + (d.size_bytes || 0), 0);
  const allSelected = filtered.length > 0 && filtered.every((d) => selectedDocIds.includes(d.id));

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) onUpload(files);
  };

  const pick = () => fileRef.current?.click();

  return (
    <div
      className={styles.page}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          if (files.length) onUpload(files);
          e.target.value = '';
        }}
      />
      {dragging && (
        <div className={styles.dropOverlay}>
          <UploadCloud size={28} strokeWidth={1.5} />
          <span>Drop files to add them to your library</span>
        </div>
      )}

      <header className={styles.topbar}>
        {!sidebarOpen && (
          <button type="button" className="icon-btn" onClick={onOpenSidebar} aria-label="Open sidebar">
            <PanelLeftOpen size={18} strokeWidth={1.75} />
          </button>
        )}
      </header>

      <main className={styles.content} id="main">
        <div className={styles.titleRow}>
          <div>
            <h1 className={styles.title}>Library</h1>
            <p className={styles.subtitle}>
              {documents.length
                ? `${pluralize(documents.length, 'document')} · ${formatBytes(totalBytes)} · stored on this machine`
                : 'Documents you add are parsed, indexed and mapped into the knowledge graph locally.'}
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={pick}>
            <Plus size={16} strokeWidth={2} /> Add documents
          </button>
        </div>

        {uploads.length > 0 && (
          <section className={styles.uploads} aria-label="Uploads">
            {uploads.map((u) => (
              <div key={u.id} className={styles.upload} data-status={u.status}>
                {u.status === 'uploading' && <span className="spinner" />}
                {(u.status === 'done' || u.status === 'duplicate') && <CheckCircle2 size={16} strokeWidth={1.75} />}
                {u.status === 'error' && <AlertCircle size={16} strokeWidth={1.75} />}
                <span className={styles.uploadName}>{u.name}</span>
                <span className={styles.uploadMsg}>
                  {u.status === 'uploading'
                    ? 'Reading and indexing…'
                    : u.status === 'duplicate'
                      ? 'Already in your library'
                      : u.message}
                </span>
              </div>
            ))}
            {uploads.every((u) => u.status !== 'uploading') && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={onDismissUploads}>
                Clear
              </button>
            )}
          </section>
        )}

        {error && (
          <div className={styles.error} role="alert">
            <AlertCircle size={16} strokeWidth={1.75} />
            <span>{error}</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onReload}>
              <RefreshCw size={14} strokeWidth={1.75} /> Retry
            </button>
          </div>
        )}

        {!loading && !error && documents.length === 0 ? (
          <button type="button" className={styles.dropzone} onClick={pick}>
            <UploadCloud size={30} strokeWidth={1.4} />
            <span className={styles.dropTitle}>Drop PDFs, Word files, text or Markdown here</span>
            <span className={styles.dropSub}>or click to browse · up to 100 MB each</span>
          </button>
        ) : (
          <>
            <div className={styles.toolbar}>
              <label className={styles.search}>
                <Search size={15} strokeWidth={1.75} aria-hidden="true" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter documents" aria-label="Filter documents" />
              </label>
              {selectedDocIds.length > 0 && (
                <div className={styles.selection}>
                  <span>{pluralize(selectedDocIds.length, 'document')} selected</span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => onSetSelection([])}>
                    Clear
                  </button>
                  <button type="button" className="btn btn-primary btn-sm" onClick={onAskSelected}>
                    <MessageSquarePlus size={14} strokeWidth={1.75} /> Ask about selected
                  </button>
                </div>
              )}
            </div>

            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.checkCol}>
                      <input
                        type="checkbox"
                        aria-label="Select all documents"
                        checked={allSelected}
                        onChange={() =>
                          onSetSelection(allSelected ? selectedDocIds.filter((id) => !filtered.some((d) => d.id === id)) : [...new Set([...selectedDocIds, ...filtered.map((d) => d.id)])])
                        }
                      />
                    </th>
                    <th>Name</th>
                    <th className={styles.numCol}>Size</th>
                    <th className={styles.numCol}>Sections</th>
                    <th>Graph</th>
                    <th>Added</th>
                    <th className={styles.actionCol}>
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {loading && !documents.length &&
                    [0, 1, 2].map((i) => (
                      <tr key={i} className={styles.skeletonRow} aria-hidden="true">
                        <td colSpan={7}>
                          <span />
                        </td>
                      </tr>
                    ))}
                  {filtered.map((d) => {
                    const selected = selectedDocIds.includes(d.id);
                    return (
                      <tr key={d.id} data-selected={selected}>
                        <td className={styles.checkCol}>
                          <input type="checkbox" aria-label={`Select ${d.filename}`} checked={selected} onChange={() => onToggleDoc(d.id)} />
                        </td>
                        <td>
                          <div className={styles.nameCell}>
                            <span className={styles.typeIcon} data-type={d.file_type}>
                              {d.file_type === 'pdf' ? <FileType2 size={16} strokeWidth={1.6} /> : <FileText size={16} strokeWidth={1.6} />}
                            </span>
                            <span className={styles.fileName} title={d.filename}>
                              {d.filename.replace(new RegExp(`\\.${d.file_type}$`, 'i'), '')}
                            </span>
                            <span className={styles.ext}>{d.file_type}</span>
                          </div>
                        </td>
                        <td className={`${styles.numCol} num`}>{formatBytes(d.size_bytes)}</td>
                        <td className={`${styles.numCol} num`}>{d.chunk_count ?? '—'}</td>
                        <td>
                          <GraphStatus doc={d} />
                        </td>
                        <td className={styles.dateCell}>{formatDate(d.upload_date)}</td>
                        <td className={styles.actionCol}>
                          <button type="button" className="icon-btn icon-btn-sm" aria-label={`Delete ${d.filename}`} title="Delete" onClick={() => setConfirm(d)}>
                            <Trash2 size={15} strokeWidth={1.75} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {!loading && query && !filtered.length && (
                    <tr>
                      <td colSpan={7} className={styles.noMatch}>
                        No documents match “{query}”.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>

      <Dialog
        open={!!confirm}
        onClose={() => !deleting && setConfirm(null)}
        title="Delete this document?"
        description={confirm ? `“${confirm.filename}” will be removed from the library, the search index and the knowledge graph. Conversations stay.` : undefined}
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setConfirm(null)} disabled={deleting}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={deleting}
              onClick={async () => {
                if (!confirm) return;
                setDeleting(true);
                try {
                  await onDelete(confirm);
                  setConfirm(null);
                } finally {
                  setDeleting(false);
                }
              }}
            >
              {deleting && <span className="spinner" />} Delete
            </button>
          </>
        }
      >
        <span />
      </Dialog>
    </div>
  );
}
