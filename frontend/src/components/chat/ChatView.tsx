import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, Download, FileDown, FileText, Globe2, Library, PanelLeftOpen, SquarePen, Upload } from 'lucide-react';
import type { AgentStep, ChatMessage, ChatSession, DocumentItem, User } from '../../api';
import { ArtifactPanel } from '../artifacts';
import type { Artifact } from '../artifacts';
import { Menu } from '../ui/Menu';
import { ModelPicker } from '../ModelPicker';
import { ThemeSwitch } from '../ThemeSwitch';
import { RingField } from '../backgrounds/RingField';
import { prefersStill, useSettings } from '../../lib/settings';
import { useTheme } from '../../lib/theme';
import { SourceViewer } from '../viewer/SourceViewer';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { AssistantMessage, UserMessage } from './Message';
import { Composer } from './Composer';
import type { ComposerProps } from './Composer';
import styles from './chat.module.css';

interface ChatViewProps extends Omit<ComposerProps, 'variant' | 'autoFocus' | 'draft'> {
  chat: ChatSession | null;
  messages: ChatMessage[];
  liveSteps: AgentStep[];
  loadingMessages: boolean;
  onRetry: (assistantIndex: number) => void;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  onNewChat: () => void;
  onExport: (format: 'pdf' | 'docx') => void;
  exporting: 'pdf' | 'docx' | null;
  onViewOnGlobe: (names: string[]) => void;
  onNavigate: (view: 'library' | 'knowledge') => void;
  user: User | null;
  /** Free answers left on the server's keys; null when they do not apply (own key, admin, local install). */
  freeAnswers?: { left: number; limit: number } | null;
  onAddKey?: () => void;
  /** A hosted server with accounts (free answers and own keys apply). */
  accountsMode?: boolean;
}

function heading(user: User | null, documents: number): string {
  const first = user?.name?.split(/\s+/)[0];
  if (!documents) return 'Start with a document';
  return first ? `What do you need, ${first}?` : 'Ask your library';
}

const shorten = (s: string, max = 28) => (s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s);

function suggestionsFor(documents: DocumentItem[]): Array<{ label: string; prompt: string }> {
  const names = documents.map((d) => d.filename.replace(/\.[^.]+$/, ''));
  if (!names.length) return [];
  const [a, b] = names;
  const out = [
    { label: `Summarize ${shorten(a)}`, prompt: `Give me a structured summary of "${a}": purpose, key findings and open questions.` },
    { label: 'Key figures', prompt: `What are the most important numbers in "${a}", and what do they measure?` },
    { label: 'Who and what is involved', prompt: `List the main people, organizations and concepts in "${a}" and how they relate.` },
  ];
  if (b) out.splice(2, 0, { label: `Compare with ${shorten(b)}`, prompt: `Compare "${a}" and "${b}". Where do they agree, and where do they conflict?` });
  return out.slice(0, 4);
}

/** "2 of 3 free answers left · Use your own key": the trial on the server's keys, and the way past it. */
function FreeAnswers({ left, limit, onAddKey }: { left: number; limit: number; onAddKey?: () => void }) {
  return (
    <p className={styles.freeAnswers} data-empty={left === 0 || undefined}>
      {left > 0 ? `${left} of ${limit} free answers left` : 'Free answers used up'}
      {onAddKey && (
        <>
          {' · '}
          <button type="button" onClick={onAddKey}>{left > 0 ? 'Use your own free key' : 'Add your own free key to keep going'}</button>
        </>
      )}
    </p>
  );
}

export function ChatView(props: ChatViewProps) {
  const {
    chat,
    messages,
    liveSteps,
    loadingMessages,
    onRetry,
    sidebarOpen,
    onOpenSidebar,
    onNewChat,
    onExport,
    exporting,
    onViewOnGlobe,
    onNavigate,
    user,
    freeAnswers,
    onAddKey,
    accountsMode = false,
    ...composer
  } = props;
  const settings = useSettings();
  const { resolved } = useTheme();
  // The navigation bar lifts off the page once the conversation scrolls under it.
  const [lifted, setLifted] = useState(false);
  // The side panel shows a chart at full size or a cited passage in its document.
  const [panel, setPanel] = useState<{ kind: 'artifact'; artifact: Artifact } | { kind: 'source'; target: ViewerTarget } | null>(null);
  const [draft, setDraft] = useState<{ text: string; nonce: number } | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const empty = !messages.length && !loadingMessages;
  const busy = composer.busy;
  const suggestions = useMemo(() => suggestionsFor(composer.documents), [composer.documents]);

  // Close the panel when switching conversations
  useEffect(() => setPanel(null), [chat?.id]);

  // Follow new content only when the reader is already at the bottom
  useEffect(() => {
    if (atBottom) endRef.current?.scrollIntoView({ block: 'end' });
  }, [messages, liveSteps, atBottom]);

  useEffect(() => {
    if (!busy) return;
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' });
  }, [busy]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
    setLifted(el.scrollTop > 4);
  };

  const header = (
    <header className={styles.header} data-lifted={(lifted && !empty) || undefined}>
      <div className={styles.headerLeft}>
        {!sidebarOpen && (
          <>
            <button type="button" className="icon-btn" onClick={onOpenSidebar} aria-label="Open sidebar" title="Open sidebar">
              <PanelLeftOpen size={18} strokeWidth={1.75} />
            </button>
            <button type="button" className="icon-btn" onClick={onNewChat} aria-label="New chat" title="New chat">
              <SquarePen size={17} strokeWidth={1.75} />
            </button>
          </>
        )}
        <h1 className={styles.chatTitle}>{!empty && chat ? chat.title : 'New chat'}</h1>
      </div>
      <div className={styles.headerRight}>
        <ModelPicker accountsMode={accountsMode} freeAnswers={freeAnswers} onAddKey={onAddKey} />
        {!empty && chat && (
          <Menu
            label="Export"
            trigger={(p) => (
              <button type="button" className="btn btn-ghost btn-sm" disabled={!!exporting} {...p}>
                {exporting ? <span className="spinner" /> : <Download size={15} strokeWidth={1.75} />}
                {exporting ? 'Exporting…' : 'Export'}
              </button>
            )}
          >
            {(close) => (
              <>
                <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onExport('pdf'); }}>
                  <FileDown size={15} strokeWidth={1.75} /> PDF report
                </button>
                <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onExport('docx'); }}>
                  <FileText size={15} strokeWidth={1.75} /> Word document
                </button>
              </>
            )}
          </Menu>
        )}
        <span className={styles.themeSwitch}><ThemeSwitch /></span>
      </div>
    </header>
  );

  return (
    <div className={styles.chatLayout} data-panel={!!panel}>
      <div className={styles.conversation} data-empty={empty || undefined}>
        {settings.backdrop !== 'off' && (
          <RingField className={styles.backdrop} dark={resolved === 'dark'} accent={settings.accent}
            still={settings.backdrop === 'still' || prefersStill(settings)} />
        )}
        {header}
        {empty ? (
          <div className={styles.hero}>
            <div className={styles.heroInner}>
              <p className={styles.heroEyebrow}>
                {composer.documents.length
                  ? `${composer.documents.length} ${composer.documents.length === 1 ? 'document' : 'documents'} in your library`
                  : 'Your library is empty'}
              </p>
              <h2 className={styles.heroTitle}>{heading(user, composer.documents.length)}</h2>
              <p className={styles.heroSub}>
                {composer.documents.length
                  ? 'Every answer cites the page it came from, and each sentence is checked against its source.'
                  : 'Add PDFs, scans, slides, spreadsheets, e-mails or recordings, then ask about them in plain language.'}
              </p>
              <Composer {...composer} variant="hero" autoFocus draft={draft} />
              {freeAnswers && <FreeAnswers {...freeAnswers} onAddKey={onAddKey} />}
              <div className={styles.suggestions}>
                {suggestions.map((s) => (
                  <button key={s.label} type="button" className="chip" onClick={() => setDraft({ text: s.prompt, nonce: Date.now() })}>
                    {s.label}
                  </button>
                ))}
                {!composer.documents.length ? (
                  <button type="button" className="chip" onClick={() => onNavigate('library')}>
                    <Upload size={14} strokeWidth={1.75} /> Add documents
                  </button>
                ) : (
                  <>
                    <button type="button" className="chip" onClick={() => onNavigate('knowledge')}>
                      <Globe2 size={14} strokeWidth={1.75} /> Explore the knowledge globe
                    </button>
                    <button type="button" className="chip" onClick={() => onNavigate('library')}>
                      <Library size={14} strokeWidth={1.75} /> Library
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className={styles.scroll} ref={scrollRef} onScroll={onScroll}>
              <div className={styles.thread} id="main" role="log" aria-label="Conversation">
                {loadingMessages && !messages.length && (
                  <div className={styles.skeleton} aria-hidden="true">
                    <span style={{ width: '40%', marginLeft: 'auto' }} />
                    <span style={{ width: '90%' }} />
                    <span style={{ width: '75%' }} />
                  </div>
                )}
                {messages.map((m, i) =>
                  m.role === 'user' ? (
                    <UserMessage key={m.id ?? `u-${i}`} message={m} />
                  ) : (
                    <AssistantMessage
                      key={m.id ?? `a-${i}`}
                      message={m}
                      liveSteps={m.pending ? liveSteps : undefined}
                      onRetry={m.error ? () => onRetry(i) : undefined}
                      onOpenArtifact={(artifact) => setPanel({ kind: 'artifact', artifact })}
                      onOpenSource={(target) => setPanel({ kind: 'source', target })}
                      onViewOnGlobe={onViewOnGlobe}
                      language={composer.language}
                    />
                  ),
                )}
                <div ref={endRef} className={styles.end} />
              </div>
            </div>
            {!atBottom && (
              <button
                type="button"
                className={styles.jump}
                aria-label="Scroll to latest"
                onClick={() => endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}
              >
                <ArrowDown size={16} strokeWidth={1.75} />
              </button>
            )}
            <div className={styles.dock}>
              <Composer {...composer} variant="dock" draft={draft} />
              {freeAnswers ? (
                <FreeAnswers {...freeAnswers} onAddKey={onAddKey} />
              ) : (
                <p className={styles.disclaimer}>Answers can contain mistakes. Every claim links to its source so you can check it.</p>
              )}
            </div>
          </>
        )}
      </div>
      <ArtifactPanel artifact={panel?.kind === 'artifact' ? panel.artifact : null} onClose={() => setPanel(null)} />
      <SourceViewer target={panel?.kind === 'source' ? panel.target : null} onClose={() => setPanel(null)} />
    </div>
  );
}
