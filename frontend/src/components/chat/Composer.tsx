import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DragEvent, FormEvent, KeyboardEvent } from 'react';
import { ArrowUp, Check, FileText, Globe2, Languages, Library, Mic, Paperclip, Square } from 'lucide-react';
import type { DocumentItem, WebMode } from '../../api';
import { SUPPORTED_LANGUAGES, voiceController } from '../../utils/voice';
import { Menu } from '../ui/Menu';
import styles from './chat.module.css';

export interface ComposerProps {
  onSend: (text: string) => void;
  onStop: () => void;
  busy: boolean;
  documents: DocumentItem[];
  selectedDocIds: string[];
  onToggleDoc: (id: string) => void;
  onClearScope: () => void;
  onUpload: (files: File[]) => void;
  uploading: boolean;
  language: string;
  onLanguageChange: (code: string) => void;
  /** When answers may use web search: when needed, always, or never */
  webMode: WebMode;
  onWebModeChange: (mode: WebMode) => void;
  variant?: 'dock' | 'hero';
  autoFocus?: boolean;
  /** Text to place into the composer (e.g. a suggestion); consumed once. */
  draft?: { text: string; nonce: number } | null;
}

const WEB_MODES: Array<{ key: WebMode; label: string; hint: string }> = [
  { key: 'auto', label: 'When needed', hint: 'recent or not in documents' },
  { key: 'on', label: 'Always', hint: 'documents + web' },
  { key: 'off', label: 'Never', hint: 'documents only' },
];

const ACCEPT = '.pdf,.docx,.txt,.md,.csv,.tsv,.xlsx,.pptx,.eml,.epub,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp,.mp3,.wav,.m4a,.ogg,.flac,.webm,.mp4';

export function Composer(props: ComposerProps) {
  const {
    onSend,
    onStop,
    busy,
    documents,
    selectedDocIds,
    onToggleDoc,
    onClearScope,
    onUpload,
    uploading,
    language,
    onLanguageChange,
    webMode,
    onWebModeChange,
    variant = 'dock',
    autoFocus,
    draft,
  } = props;
  const [text, setText] = useState('');
  const [listening, setListening] = useState(false);
  const [dragging, setDragging] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (draft) {
      setText(draft.text);
      taRef.current?.focus();
    }
  }, [draft]);

  useEffect(() => {
    if (autoFocus) taRef.current?.focus();
  }, [autoFocus]);

  // Grow with content up to a cap
  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, Math.round(window.innerHeight * 0.38))}px`;
  }, [text]);

  // "/" focuses the composer from anywhere outside a text field
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        taRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => () => voiceController.stopListening(), []);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const toggleVoice = () => {
    if (listening) {
      voiceController.stopListening();
      setListening(false);
      return;
    }
    voiceController.setLanguage(language);
    setListening(true);
    voiceController.startListening(
      (transcript) => setText(transcript),
      () => setListening(false),
      () => setListening(false),
    );
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) onUpload(files);
  };

  const scopeLabel = selectedDocIds.length
    ? selectedDocIds.length === 1
      ? documents.find((d) => d.id === selectedDocIds[0])?.filename ?? '1 document'
      : `${selectedDocIds.length} documents`
    : 'All documents';
  const lang = SUPPORTED_LANGUAGES.find((l) => l.code === language) ?? SUPPORTED_LANGUAGES[0];
  const canSend = text.trim().length > 0 && !busy;

  return (
    <form
      className={styles.composer}
      data-variant={variant}
      data-dragging={dragging}
      onSubmit={submit}
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
      {dragging && <div className={styles.dropHint}>Drop to add to your library</div>}
      <label htmlFor="composer-input" className="visually-hidden">
        Ask about your documents
      </label>
      <textarea
        id="composer-input"
        ref={taRef}
        className={styles.input}
        rows={1}
        value={text}
        placeholder={listening ? 'Listening…' : 'Ask anything about your documents'}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
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
          <button
            type="button"
            className="icon-btn"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            aria-label="Add documents"
            title="Add documents (PDF, scans, images, Word, spreadsheets, slides, email, text)"
          >
            {uploading ? <span className="spinner" /> : <Paperclip size={17} strokeWidth={1.75} />}
          </button>

          <Menu
            label="Document scope"
            side="top"
            align="start"
            trigger={(p) => (
              <button type="button" className={`chip ${styles.scopeChip}`} data-active={selectedDocIds.length > 0} {...p}>
                <Library size={14} strokeWidth={1.75} />
                <span className={styles.scopeText}>{scopeLabel}</span>
              </button>
            )}
          >
            {() => (
              <div className={styles.scopeMenu}>
                <div className="menu-label">Answer from</div>
                <button type="button" role="menuitemradio" aria-checked={!selectedDocIds.length} className="menu-item" onClick={onClearScope}>
                  <Library size={15} strokeWidth={1.75} /> All documents
                  {!selectedDocIds.length && <Check size={15} strokeWidth={2} className="menu-hint" />}
                </button>
                {documents.length > 0 && <div className="menu-sep" />}
                {documents.map((d) => {
                  const on = selectedDocIds.includes(d.id);
                  return (
                    <button
                      key={d.id}
                      type="button"
                      role="menuitemcheckbox"
                      aria-checked={on}
                      className="menu-item"
                      onClick={() => onToggleDoc(d.id)}
                      title={d.filename}
                    >
                      <FileText size={15} strokeWidth={1.75} />
                      <span className={styles.scopeDoc}>{d.filename}</span>
                      {on && <Check size={15} strokeWidth={2} className="menu-hint" />}
                    </button>
                  );
                })}
                {!documents.length && <div className="menu-label">No documents yet. Attach one to begin.</div>}
              </div>
            )}
          </Menu>
          <Menu
            label="Web search"
            side="top"
            align="start"
            trigger={(p) => (
              <button
                type="button"
                className={`chip ${styles.scopeChip}`}
                data-active={webMode === 'on'}
                title="Web search"
                aria-label={`Web search: ${WEB_MODES.find((m) => m.key === webMode)?.label}`}
                {...p}
              >
                <Globe2 size={14} strokeWidth={1.75} />
                <span className={styles.scopeText}>{webMode === 'on' ? 'Web' : webMode === 'off' ? 'No web' : 'Web: auto'}</span>
              </button>
            )}
          >
            {(close) => (
              <>
                <div className="menu-label">Search the web</div>
                {WEB_MODES.map((m) => (
                  <button
                    key={m.key}
                    type="button"
                    role="menuitemradio"
                    aria-checked={webMode === m.key}
                    className="menu-item"
                    onClick={() => {
                      onWebModeChange(m.key);
                      close();
                    }}
                  >
                    <span>{m.label}</span>
                    <span className="menu-hint">{webMode === m.key ? <Check size={15} strokeWidth={2} /> : m.hint}</span>
                  </button>
                ))}
              </>
            )}
          </Menu>
        </div>

        <div className={styles.toolbarRight}>
          <Menu
            label="Answer language"
            side="top"
            trigger={(p) => (
              <button type="button" className={`chip ${styles.langChip}`} title="Answer language" {...p}>
                <Languages size={14} strokeWidth={1.75} />
                <span>{lang.code === 'en' ? 'English' : lang.nativeName}</span>
              </button>
            )}
          >
            {(close) => (
              <>
                <div className="menu-label">Answer in</div>
                {SUPPORTED_LANGUAGES.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    role="menuitemradio"
                    aria-checked={language === l.code}
                    className="menu-item"
                    onClick={() => {
                      onLanguageChange(l.code);
                      close();
                    }}
                  >
                    <span>{l.code === 'en' ? 'English' : l.nativeName}</span>
                    <span className="menu-hint">{language === l.code ? <Check size={15} strokeWidth={2} /> : l.name}</span>
                  </button>
                ))}
              </>
            )}
          </Menu>

          {voiceController.isSpeechSupported() && (
            <button
              type="button"
              className={`icon-btn ${styles.micButton}`}
              aria-pressed={listening}
              aria-label={listening ? 'Stop voice input' : 'Voice input'}
              title={listening ? 'Stop listening' : 'Speak your question'}
              onClick={toggleVoice}
            >
              <Mic size={17} strokeWidth={1.75} />
            </button>
          )}

          {busy ? (
            <button type="button" className={styles.send} onClick={onStop} aria-label="Stop" title="Stop">
              <Square size={12} strokeWidth={0} fill="currentColor" />
            </button>
          ) : (
            <button type="submit" className={styles.send} disabled={!canSend} aria-label="Send" title="Send (Enter)">
              <ArrowUp size={17} strokeWidth={2.2} />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
