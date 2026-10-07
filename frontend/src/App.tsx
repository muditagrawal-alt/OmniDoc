import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { AgentStep, ChatMessage, ChatSession, DocumentItem, User } from './api';
import { payloadToMetadata } from './lib/normalize';
import { Sidebar } from './components/Sidebar';
import type { View } from './components/Sidebar';
import { ChatView } from './components/chat/ChatView';
import { LibraryView } from './components/library/LibraryView';
import type { UploadItem } from './components/library/LibraryView';
import { ProfileDialog } from './components/ProfileDialog';
import { ToastProvider, useToast } from './components/ui/Toast';
import styles from './App.module.css';

const MOBILE_QUERY = '(max-width: 900px)';

// The globe pulls in three.js; load it only when the knowledge view opens.
const KnowledgeView = lazy(() => import('./components/knowledge/KnowledgeView').then((m) => ({ default: m.KnowledgeView })));
const VIEWS: View[] = ['chat', 'library', 'knowledge'];

function viewFromHash(): View {
  const v = window.location.hash.replace(/^#\/?/, '').split('/')[0] as View;
  return VIEWS.includes(v) ? v : 'chat';
}

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const on = () => setMobile(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return mobile;
}

interface InFlight {
  chatId: string;
  query: string;
  steps: AgentStep[];
  controller: AbortController;
}

function Shell() {
  const toast = useToast();
  const isMobile = useIsMobile();
  const [view, setView] = useState<View>(viewFromHash);
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia(MOBILE_QUERY).matches);

  const [user, setUser] = useState<User | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);

  const [chats, setChats] = useState<ChatSession[]>([]);
  const [chatsLoading, setChatsLoading] = useState(true);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [inflight, setInflight] = useState<InFlight | null>(null);
  const inflightRef = useRef<InFlight | null>(null);
  const activeChatRef = useRef<string | null>(null);

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [language, setLanguage] = useState('en');
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null);
  const [globeFocus, setGlobeFocus] = useState<string[] | undefined>(undefined);

  activeChatRef.current = activeChatId;

  // ---- navigation ----------------------------------------------------------
  const navigate = useCallback(
    (next: View) => {
      setView(next);
      const hash = `#/${next}`;
      if (window.location.hash !== hash) window.history.pushState(null, '', hash);
      if (isMobile) setSidebarOpen(false);
    },
    [isMobile],
  );

  useEffect(() => {
    const onPop = () => setView(viewFromHash());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  useEffect(() => {
    setSidebarOpen(!isMobile);
  }, [isMobile]);

  // ---- data loading --------------------------------------------------------
  const loadChats = useCallback(async () => {
    try {
      setChats(await api.getChats());
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setChatsLoading(false);
    }
  }, [toast]);

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await api.getDocuments();
      setDocuments(docs);
      setDocsError(null);
      setSelectedDocIds((sel) => sel.filter((id) => docs.some((d) => d.id === id)));
    } catch (e) {
      setDocsError((e as Error).message);
    } finally {
      setDocsLoading(false);
    }
  }, []);

  useEffect(() => {
    api.getMe().then(setUser);
    loadChats();
    loadDocuments();
  }, [loadChats, loadDocuments]);

  // Poll while knowledge-graph extraction is running in the background
  const extracting = documents.some((d) => d.graph_status && ['queued', 'running'].includes(d.graph_status.status));
  useEffect(() => {
    if (!extracting) return;
    const t = window.setInterval(loadDocuments, 3000);
    return () => window.clearInterval(t);
  }, [extracting, loadDocuments]);

  useEffect(() => {
    if (!activeChatId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoadingMessages(true);
    api
      .getChat(activeChatId)
      .then((data) => {
        if (!cancelled) setMessages(data.messages || []);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setActiveChatId(null);
          loadChats();
        } else toast(e.message, 'bad');
      })
      .finally(() => !cancelled && setLoadingMessages(false));
    return () => {
      cancelled = true;
    };
  }, [activeChatId, loadChats, toast]);

  // ---- chats ---------------------------------------------------------------
  const newChat = useCallback(() => {
    setActiveChatId(null);
    setMessages([]);
    navigate('chat');
  }, [navigate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        newChat();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [newChat]);

  const selectChat = (id: string) => {
    setActiveChatId(id);
    navigate('chat');
  };

  const renameChat = async (id: string, title: string) => {
    setChats((cs) => cs.map((c) => (c.id === id ? { ...c, title } : c)));
    try {
      await api.renameChat(id, title);
    } catch (e) {
      toast((e as Error).message, 'bad');
      loadChats();
    }
  };

  const deleteChat = async (id: string) => {
    const previous = chats;
    setChats((cs) => cs.filter((c) => c.id !== id));
    if (activeChatId === id) setActiveChatId(null);
    try {
      await api.deleteChat(id);
    } catch (e) {
      setChats(previous);
      toast((e as Error).message, 'bad');
    }
  };

  // ---- asking --------------------------------------------------------------
  const send = useCallback(
    async (query: string, opts?: { chatId?: string | null; docIds?: string[] }) => {
      if (inflightRef.current) return;
      let chatId = opts && 'chatId' in opts ? opts.chatId ?? null : activeChatRef.current;
      try {
        if (!chatId) {
          const chat = await api.createChat();
          setChats((cs) => [chat, ...cs]);
          chatId = chat.id;
          activeChatRef.current = chat.id;
          setActiveChatId(chat.id);
          setMessages([]);
        }
      } catch (e) {
        toast((e as Error).message, 'bad');
        return;
      }

      const controller = new AbortController();
      const flight: InFlight = { chatId, query, steps: [], controller };
      inflightRef.current = flight;
      setInflight(flight);

      const pending: ChatMessage = { role: 'assistant', content: '', pending: true };
      setMessages((ms) => [...ms, { role: 'user', content: query }, pending]);

      const replacePending = (msg: ChatMessage) => {
        if (activeChatRef.current !== chatId) return;
        setMessages((ms) => {
          const idx = ms.findIndex((m) => m.pending);
          if (idx === -1) return ms;
          const copy = ms.slice();
          copy[idx] = msg;
          return copy;
        });
      };

      try {
        const result = await api.streamQuery(
          chatId,
          { query, document_ids: opts?.docIds ?? selectedDocIds, language },
          {
            signal: controller.signal,
            onStep: (step) => {
              flight.steps = [...flight.steps, step];
              setInflight({ ...flight });
            },
          },
        );
        replacePending({
          id: result.message_id,
          role: 'assistant',
          content: result.answer,
          metadata: payloadToMetadata(result),
          timestamp: new Date().toISOString(),
        });
        loadChats();
      } catch (e) {
        const aborted = (e as Error).name === 'AbortError';
        replacePending({ role: 'assistant', content: '', error: aborted ? 'Stopped before an answer was ready.' : (e as Error).message });
      } finally {
        inflightRef.current = null;
        setInflight(null);
      }
    },
    [language, loadChats, selectedDocIds, toast],
  );

  const stop = () => inflightRef.current?.controller.abort();

  const retry = (assistantIndex: number) => {
    const userMsg = messages[assistantIndex - 1];
    if (!userMsg || userMsg.role !== 'user') return;
    setMessages((ms) => ms.slice(0, assistantIndex - 1));
    send(userMsg.content);
  };

  const askAboutEntity = (name: string) => {
    navigate('chat');
    send(`What do my documents say about ${name}? Explain how it relates to the other entities it is connected to.`, { chatId: null, docIds: [] });
  };

  const askSelected = () => {
    setActiveChatId(null);
    setMessages([]);
    navigate('chat');
  };

  // ---- documents -----------------------------------------------------------
  const upload = useCallback(
    async (files: File[]) => {
      for (const file of files) {
        const id = `${file.name}-${file.size}-${file.lastModified}`;
        setUploads((u) => [...u.filter((x) => x.id !== id), { id, name: file.name, status: 'uploading' }]);
        try {
          const res = await api.uploadDocument(file);
          setUploads((u) =>
            u.map((x) =>
              x.id === id
                ? { ...x, status: res.duplicate ? 'duplicate' : 'done', message: `${res.chunk_count} sections indexed` }
                : x,
            ),
          );
          if (!res.duplicate) toast(`${file.name} is ready to ask about`, 'good');
        } catch (e) {
          setUploads((u) => u.map((x) => (x.id === id ? { ...x, status: 'error', message: (e as Error).message } : x)));
          toast(`${file.name}: ${(e as Error).message}`, 'bad');
        }
        loadDocuments();
      }
    },
    [loadDocuments, toast],
  );

  const deleteDocument = async (doc: DocumentItem) => {
    try {
      await api.deleteDocument(doc.id);
      toast(`Deleted ${doc.filename}`);
      setSelectedDocIds((s) => s.filter((id) => id !== doc.id));
      loadDocuments();
    } catch (e) {
      toast((e as Error).message, 'bad');
    }
  };

  const toggleDoc = (id: string) => setSelectedDocIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  // ---- export --------------------------------------------------------------
  const exportChat = async (format: 'pdf' | 'docx') => {
    const chat = chats.find((c) => c.id === activeChatId);
    if (!chat) return;
    setExporting(format);
    try {
      const blob = await api.exportChat(chat.id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(chat.title || 'OmniDoc').replace(/[\\/:*?"<>|]+/g, '').trim() || 'OmniDoc'}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setExporting(null);
    }
  };

  const activeChat = chats.find((c) => c.id === activeChatId) ?? null;
  const busy = !!inflight;
  const liveSteps = inflight && inflight.chatId === activeChatId ? inflight.steps : [];

  return (
    <div className={styles.app}>
      <Sidebar
        open={sidebarOpen}
        isMobile={isMobile}
        onClose={() => setSidebarOpen(false)}
        view={view}
        onNavigate={navigate}
        chats={chats}
        chatsLoading={chatsLoading}
        activeChatId={activeChatId}
        onSelectChat={selectChat}
        onNewChat={newChat}
        onRenameChat={renameChat}
        onDeleteChat={deleteChat}
        user={user}
        onOpenProfile={() => setProfileOpen(true)}
        onSignOut={async () => {
          await api.logout();
          setUser(null);
          setActiveChatId(null);
          loadChats();
        }}
        documentCount={documents.length}
      />
      <div className={styles.main}>
        {view === 'chat' && (
          <ChatView
            chat={activeChat}
            messages={messages}
            liveSteps={liveSteps}
            loadingMessages={loadingMessages}
            onRetry={retry}
            sidebarOpen={sidebarOpen}
            onOpenSidebar={() => setSidebarOpen(true)}
            onNewChat={newChat}
            onExport={exportChat}
            exporting={exporting}
            onViewOnGlobe={(names) => {
              setGlobeFocus(names);
              navigate('knowledge');
            }}
            onNavigate={navigate}
            user={user}
            onSend={(q) => send(q)}
            onStop={stop}
            busy={busy}
            documents={documents}
            selectedDocIds={selectedDocIds}
            onToggleDoc={toggleDoc}
            onClearScope={() => setSelectedDocIds([])}
            onUpload={upload}
            uploading={uploads.some((u) => u.status === 'uploading')}
            language={language}
            onLanguageChange={setLanguage}
          />
        )}
        {view === 'library' && (
          <LibraryView
            documents={documents}
            loading={docsLoading}
            error={docsError}
            onReload={loadDocuments}
            onUpload={upload}
            uploads={uploads}
            onDismissUploads={() => setUploads([])}
            onDelete={deleteDocument}
            selectedDocIds={selectedDocIds}
            onToggleDoc={toggleDoc}
            onSetSelection={setSelectedDocIds}
            onAskSelected={askSelected}
            sidebarOpen={sidebarOpen}
            onOpenSidebar={() => setSidebarOpen(true)}
          />
        )}
        {view === 'knowledge' && (
          <div className={styles.knowledge}>
            <Suspense fallback={null}>
              <KnowledgeView
                onAskAboutEntity={askAboutEntity}
                onOpenLibrary={() => navigate('library')}
                focusEntityNames={globeFocus}
                sidebarOpen={sidebarOpen}
                onOpenSidebar={() => setSidebarOpen(true)}
              />
            </Suspense>
          </div>
        )}
      </div>
      <ProfileDialog
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        onSignedIn={(u) => {
          setUser(u);
          setActiveChatId(null);
          loadChats();
          toast(`Signed in as ${u.name}`, 'good');
        }}
      />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
