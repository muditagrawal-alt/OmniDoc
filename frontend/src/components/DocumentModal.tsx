import React, { useState, useEffect } from 'react';
import { UploadCloud, FileText, CheckCircle, X, RefreshCw, Layers, Trash2 } from 'lucide-react';
import { api } from '../api';
import type { DocumentItem } from '../api';

interface DocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedDocIds: string[];
  onToggleDocSelect: (docId: string) => void;
}

export const DocumentModal: React.FC<DocumentModalProps> = ({
  isOpen,
  onClose,
  selectedDocIds,
  onToggleDocSelect,
}) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDocuments = async () => {
    setLoading(true);
    try {
      const docs = await api.getDocuments();
      setDocuments(docs);
    } catch (err: any) {
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchDocuments();
    }
  }, [isOpen]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(file);
      await fetchDocuments();
    } catch (err: any) {
      setError(err.message || 'Upload and indexing failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDocument = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation();
    try {
      await api.deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      if (selectedDocIds.includes(docId)) {
        onToggleDocSelect(docId);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete document');
    }
  };

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 1000,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(8px)',
      padding: '1.5rem',
      animation: 'fadeIn 0.2s ease-out'
    }}>
      <div style={{
        position: 'relative',
        width: '100%',
        maxWidth: '560px',
        maxHeight: '85vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-medium)',
        borderRadius: 'var(--radius-xl)',
        boxShadow: 'var(--shadow-lg)',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '1.25rem 1.5rem',
          borderBottom: '1px solid var(--border-subtle)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <Layers size={20} style={{ color: 'var(--accent-primary)' }} />
            <div>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Document Knowledge Base</h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Ingest PDF, DOCX, & Reports into LanceDB & Kùzu Graph
              </p>
            </div>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)', padding: '0.25rem' }}>
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '1.25rem 1.5rem', overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{
              backgroundColor: 'rgba(244, 63, 94, 0.1)',
              border: '1px solid var(--accent-rose)',
              borderRadius: 'var(--radius-md)',
              padding: '0.65rem',
              fontSize: '0.82rem',
              color: '#fda4af',
              marginBottom: '1rem'
            }}>
              {error}
            </div>
          )}

          {/* Upload Area */}
          <label style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.6rem',
            padding: '1.5rem 1rem',
            border: '2px dashed var(--border-medium)',
            borderRadius: 'var(--radius-lg)',
            backgroundColor: 'var(--bg-input)',
            cursor: uploading ? 'not-allowed' : 'pointer',
            transition: 'var(--transition-fast)',
            marginBottom: '1.5rem'
          }}
          onMouseEnter={(e) => e.currentTarget.style.borderColor = 'var(--accent-primary)'}
          onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--border-medium)'}
          >
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md"
              onChange={handleFileUpload}
              disabled={uploading}
              style={{ display: 'none' }}
            />
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '42px',
              height: '42px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              color: 'var(--accent-primary)',
            }}>
              {uploading ? <RefreshCw size={20} className="animate-spin" /> : <UploadCloud size={20} />}
            </div>
            <div style={{ textAlign: 'center' }}>
              <span style={{ fontWeight: 500, fontSize: '0.9rem', color: 'var(--text-primary)' }}>
                {uploading ? 'Parsing & Indexing Triples...' : 'Click to Upload Document'}
              </span>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                PDF, Word (.docx), Markdown, or Plain Text
              </p>
            </div>
          </label>

          {/* Document List */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.65rem' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Indexed Documents ({documents.length})
            </span>
            <button
              onClick={fetchDocuments}
              style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.75rem', color: 'var(--accent-primary)' }}
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>

          {documents.length === 0 ? (
            <div style={{
              textAlign: 'center',
              padding: '2rem 1rem',
              color: 'var(--text-muted)',
              fontSize: '0.85rem'
            }}>
              No documents uploaded yet. Upload a 10-K, scientific paper, or manual to begin agentic reasoning.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {documents.map((doc) => {
                const isSelected = selectedDocIds.includes(doc.id);
                const sizeKb = Math.round(doc.size_bytes / 1024);
                return (
                  <div
                    key={doc.id}
                    onClick={() => onToggleDocSelect(doc.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.7rem 0.85rem',
                      backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-surface-elevated)',
                      border: `1px solid ${isSelected ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                      borderRadius: 'var(--radius-md)',
                      cursor: 'pointer',
                      transition: 'var(--transition-fast)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', overflow: 'hidden' }}>
                      <FileText size={16} style={{ color: isSelected ? 'var(--accent-primary)' : 'var(--text-muted)', flexShrink: 0 }} />
                      <div style={{ overflow: 'hidden' }}>
                        <div style={{
                          fontSize: '0.84rem',
                          fontWeight: 500,
                          color: 'var(--text-primary)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>
                          {doc.filename}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.1rem' }}>
                          {sizeKb} KB · {doc.upload_date}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        fontSize: '0.74rem',
                        color: isSelected ? 'var(--accent-primary)' : 'var(--text-dim)',
                        fontWeight: 500
                      }}>
                        <CheckCircle size={15} style={{ opacity: isSelected ? 1 : 0.3 }} />
                        <span>{isSelected ? 'Active' : 'Include'}</span>
                      </div>

                      <button
                        onClick={(e) => handleDeleteDocument(e, doc.id)}
                        title="Delete Document"
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '0.3rem',
                          borderRadius: 'var(--radius-sm)',
                          color: 'var(--text-dim)',
                          backgroundColor: 'transparent',
                          transition: 'var(--transition-fast)'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.color = 'var(--accent-rose)';
                          e.currentTarget.style.backgroundColor = 'rgba(244, 63, 94, 0.12)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.color = 'var(--text-dim)';
                          e.currentTarget.style.backgroundColor = 'transparent';
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.85rem 1.5rem',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: 'var(--bg-app)'
        }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            {selectedDocIds.length === 0 ? 'Searching across all knowledge' : `Scoped to ${selectedDocIds.length} document(s)`}
          </span>
          <button
            onClick={onClose}
            style={{
              padding: '0.45rem 1rem',
              backgroundColor: 'var(--accent-primary)',
              borderRadius: 'var(--radius-md)',
              color: '#ffffff',
              fontSize: '0.82rem',
              fontWeight: 500
            }}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
