import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { AgentStep, AuthMethods, ChatMessage, ChatSession, DocumentItem, Source, User, WebMode } from './api';
import { payloadToMetadata } from './lib/normalize';
import { Sidebar } from './components/Sidebar';
import type { View } from './components/Sidebar';
import { AppRail } from './components/AppRail';
import { SettingsPanel } from './components/SettingsPanel';
import { ProvidersDialog } from './components/ProvidersDialog';
import { prefersStill, setSetting, useSettings } from './lib/settings';
import { useTheme } from './lib/theme';
import { CloudField } from './components/backgrounds/CloudField';
import { ChatView } from './components/chat/ChatView';
import { LibraryView } from './components/library/LibraryView';
import type { UploadItem } from './components/library/LibraryView';
import { ExtractView } from './components/extract/ExtractView';
import { CompareView } from './components/compare/CompareView';
import { SearchView } from './components/views/SearchView';
import { TablesView } from './components/views/TablesView';
import { RecordsView } from './components/views/RecordsView';
import { TimelineView } from './components/views/TimelineView';
import { PrivacyView } from './components/views/PrivacyView';
import { ConnectView } from './components/views/ConnectView';
import { AdminView } from './components/views/AdminView';
import { ProfileDialog } from './components/ProfileDialog';
import { SignIn } from './components/SignIn';
import { AccountDialog } from './components/AccountDialog';
import { NoticesDialog } from './components/NoticesDialog';
import { KeysDialog } from './components/KeysDialog';
import { Tour } from './components/Tour';
import { ToastProvider, useToast } from './components/ui/Toast';
import styles from './App.module.css';

const MOBILE_QUERY = '(max-width: 900px)';

// The globe pulls in three.js; load it only when the knowledge view opens.
const KnowledgeView = lazy(() => import('./components/knowledge/KnowledgeView').then((m) => ({ default: m.KnowledgeView })));
// The product page is its own chunk: people using the app never download it.
const Landing = lazy(() => import('./landing/Landing'));
const VIEWS: View[] = ['chat', 'search', 'library', 'extract', 'compare', 'tables', 'records', 'timeline', 'privacy', 'knowledge', 'connect', 'admin'];

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
  // A hosted server with accounts shows the sign-in page until a session exists; a local install never does.
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authTicket, setAuthTicket] = useState<string | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [noticesOpen, setNoticesOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  // Signed-out visitors see the product page; "Sign in" or "Create a free account" opens sign-in.
  const [signInStep, setSignInStep] = useState<'start' | 'signup' | null>(() =>
    window.location.pathname.startsWith('/signin') ? 'start' : null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [keysOpen, setKeysOpen] = useState(false);
  const [keysReason, setKeysReason] = useState<string | null>(null);
  const [freeAnswers, setFreeAnswers] = useState<{ left: number; limit: number } | null>(null);

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
  // Answer language, web search and effort are preferences kept in this browser (Settings).
  const settings = useSettings();
  const { resolved } = useTheme();
  const { language, webMode, effort } = settings;
  const setLanguage = (code: string) => setSetting('language', code);
  const setWebMode = (mode: WebMode) => setSetting('webMode', mode);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [providersOpen, setProvidersOpen] = useState(false);
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null);
  const [globeFocus, setGlobeFocus] = useState<string[] | undefined>(undefined);
  // The Extract view stays mounted once opened, so a running extraction and its results survive navigation.
  const [extractOpened, setExtractOpened] = useState(() => viewFromHash() === 'extract');
  if (view === 'extract' && !extractOpened) setExtractOpened(true);

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
    let cancelled = false;
    (async () => {
      const m = await api.authMethods();
      if (m.accounts) {
        const back = api.takeRedirect(); // back from Google or GitHub sign-in, or from linking one
        if (back.error) setAuthError(back.error);
        if (back.mfa) setAuthTicket(back.mfa);
        if (back.error || back.mfa) setSignInStep('start');
        if (back.linked) {
          toast(`${back.linked === 'github' ? 'GitHub' : 'Google'} is now linked to your account`, 'good');
          setAccountOpen(true);
        }
      }
      const u = await api.getMe();
      if (cancelled) return;
      setUser(u);
      setMethods(m);
      if (!m.accounts || u) {
        loadChats();
        loadDocuments();
      }
    })();
    api.onUnauthorized = () => setUser(null);
    // The free answers are used up: ask for the user's own key, right where they are.
    api.onKeyRequired = (message) => {
      setKeysReason(message);
      setKeysOpen(true);
    };
    return () => {
      cancelled = true;
    };
  }, [loadChats, loadDocuments, toast]);

  // Unread notices (new sign-ins, account changes, What's new), checked on sign-in and every few minutes.
  const accountsOn = !!methods?.accounts;
  const signedInId = user?.id;
  const guestSession = user?.kind === 'guest';
  useEffect(() => {
    if (!accountsOn || !signedInId || guestSession) return;
    const check = () => api.listNotices().then((d) => setUnread(d.unread)).catch(() => undefined);
    check();
    const t = window.setInterval(check, 5 * 60_000);
    return () => window.clearInterval(t);
  }, [accountsOn, signedInId, guestSession]);
  const clearUnread = useCallback(() => setUnread(0), []);

  // The browser's back button moves between the product page and sign-in.
  useEffect(() => {
    const onPop = () => setSignInStep(window.location.pathname.startsWith('/signin') ? 'start' : null);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  // Free answers left on the server's keys (none shown once the user's own key answers).
  const refreshFreeAnswers = useCallback(() => {
    if (!accountsOn || !signedInId) return;
    api.getAccount()
      .then((a) => setFreeAnswers(a.trial && !a.own_keys?.in_use.length ? { left: Math.max(0, a.trial.limit - a.trial.used), limit: a.trial.limit } : null))
      .catch(() => undefined);
  }, [accountsOn, signedInId]);
  useEffect(() => {
    refreshFreeAnswers();
  }, [refreshFreeAnswers]);

  // Poll while summaries or knowledge-graph extraction run in the background
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
    // A chat created by send() is being answered right now: its messages live here, and the
    // server has nothing newer (loading would replace the streaming answer).
    if (inflightRef.current?.chatId === activeChatId) return;
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
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setSettingsOpen((o) => !o);
      }
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        navigate('search');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [newChat, navigate]);

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

  const clearChats = async () => {
    for (const c of chats) await api.deleteChat(c.id);
    setChats([]);
    setActiveChatId(null);
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

      const updatePending = (change: (m: ChatMessage) => ChatMessage) => {
        if (activeChatRef.current !== chatId) return;
        setMessages((ms) => {
          const idx = ms.findIndex((m) => m.pending);
          if (idx === -1) return ms;
          const copy = ms.slice();
          copy[idx] = change(copy[idx]);
          return copy;
        });
      };
      const replacePending = (msg: ChatMessage) => updatePending(() => msg);

      // Streamed text arrives in many small pieces; apply them once per frame.
      let buffered = '';
      let frame = 0;
      const flush = () => {
        frame = 0;
        const piece = buffered;
        buffered = '';
        if (piece) updatePending((m) => ({ ...m, content: m.content + piece }));
      };
      const withSources = (sources: Source[]) => (m: ChatMessage): ChatMessage => ({
        ...m,
        metadata: { ...(m.metadata ?? {}), sources },
      });

      try {
        const result = await api.streamQuery(
          chatId,
          { query, document_ids: opts?.docIds ?? selectedDocIds, language, web: webMode, effort, model: settings.model || undefined },
          {
            signal: controller.signal,
            onStep: (step) => {
              flight.steps = [...flight.steps, step];
              setInflight({ ...flight });
            },
            onSources: (sources) => updatePending(withSources(sources)),
            onDelta: (text) => {
              buffered += text;
              if (!frame) frame = requestAnimationFrame(flush);
            },
            onReset: (sources) => {
              buffered = '';
              if (frame) cancelAnimationFrame(frame);
              frame = 0;
              updatePending((m) => ({ ...withSources(sources)(m), content: '' }));
            },
          },
        );
        if (frame) cancelAnimationFrame(frame);
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
        refreshFreeAnswers();
      }
    },
    [language, loadChats, selectedDocIds, toast, webMode, effort, settings.model, refreshFreeAnswers],
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

  /** A question typed in Search, asked in a new chat (an answer, which uses a model). */
  const askFromSearch = (question: string) => {
    setActiveChatId(null);
    setMessages([]);
    navigate('chat');
    send(question, { chatId: null });
  };

  const askSelected = () => {
    setActiveChatId(null);
    setMessages([]);
    navigate('chat');
  };

  // ---- documents -----------------------------------------------------------
  const guest = user?.kind === 'guest';
  const READ_ONLY = 'The demo is read-only. Sign in to add your own documents.';
  const upload = useCallback(
    async (files: File[]) => {
      if (guest) {
        toast(READ_ONLY);
        return;
      }
      for (const file of files) {
        const id = `${file.name}-${file.size}-${file.lastModified}`;
        setUploads((u) => [...u.filter((x) => x.id !== id), { id, name: file.name, status: 'uploading' }]);
        try {
          const res = await api.uploadDocument(file);
          const parts = [`${res.chunk_count} sections indexed`];
          if (res.ocr_pages) parts.push(`${res.ocr_pages} ${res.ocr_pages === 1 ? 'page' : 'pages'} read with OCR`);
          if (res.table_count) parts.push(`${res.table_count} ${res.table_count === 1 ? 'table' : 'tables'}`);
          setUploads((u) =>
            u.map((x) =>
              x.id === id
                ? { ...x, status: res.duplicate ? 'duplicate' : res.warning ? 'error' : 'done', message: res.warning || parts.join(' · ') }
                : x,
            ),
          );
          if (res.warning) toast(`${file.name}: ${res.warning}`, 'bad');
          else if (!res.duplicate) toast(`${file.name} is ready to ask about`, 'good');
        } catch (e) {
          setUploads((u) => u.map((x) => (x.id === id ? { ...x, status: 'error', message: (e as Error).message } : x)));
          toast(`${file.name}: ${(e as Error).message}`, 'bad');
        }
        loadDocuments();
      }
    },
    [loadDocuments, toast, guest],
  );

  const importUrl = useCallback(
    async (url: string) => {
      if (guest) {
        toast(READ_ONLY);
        return;
      }
      const id = `url-${url}`;
      setUploads((u) => [...u.filter((x) => x.id !== id), { id, name: url, status: 'uploading' }]);
      try {
        const res = await api.importUrl(url);
        setUploads((u) => u.map((x) => (x.id === id ? { ...x, name: res.filename, status: res.duplicate ? 'duplicate' : 'done', message: `${res.chunk_count} sections indexed` } : x)));
        if (!res.duplicate) toast(`${res.filename} is ready to ask about`, 'good');
      } catch (e) {
        setUploads((u) => u.map((x) => (x.id === id ? { ...x, status: 'error', message: (e as Error).message } : x)));
        toast((e as Error).message, 'bad');
      }
      loadDocuments();
    },
    [loadDocuments, toast, guest],
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

  if (!methods) return <div className={styles.app} aria-busy="true" />;
  const enterApp = (u: User) => {
    setUser(u);
    setAuthError(null);
    setAuthTicket(null);
    setSignInStep(null);
    setActiveChatId(null);
    if (window.location.pathname !== '/') window.history.replaceState(null, '', '/');
    loadChats();
    loadDocuments();
  };

  if (methods.accounts && !user && signInStep === null) {
    const tryDemo = async () => {
      setDemoBusy(true);
      setDemoError(null);
      try {
        const result = await api.startGuest();
        if ('user' in result) enterApp(result.user);
      } catch (e) {
        setDemoError((e as Error).message);
      } finally {
        setDemoBusy(false);
      }
    };
    return (
      <Suspense fallback={<div className={styles.app} aria-busy="true" />}>
        <Landing methods={methods} demoBusy={demoBusy} demoError={demoError} onTryDemo={tryDemo}
          onSignIn={(step) => {
            setSignInStep(step);
            window.history.pushState(null, '', '/signin');
          }} />
      </Suspense>
    );
  }
  if (methods.accounts && !user) {
    return (
      <SignIn
        methods={methods}
        initialError={authError}
        initialTicket={authTicket}
        initialStep={signInStep ?? 'start'}
        onBack={() => {
          setSignInStep(null);
          setAuthError(null);
          window.history.pushState(null, '', '/');
        }}
        onSignedIn={enterApp}
      />
    );
  }

  const signOut = async () => {
    const wasGuest = user?.kind === 'guest';
    await api.logout();
    setUser(null);
    // Leaving the demo goes straight to sign-in; signing out returns to the product page.
    setSignInStep(wasGuest ? 'start' : null);
    window.history.replaceState(null, '', wasGuest ? '/signin' : '/');
    setAccountOpen(false);
    setActiveChatId(null);
    setChats([]);
    setDocuments([]);
    if (!methods.accounts) loadChats();
  };

  // Desktop shows the icon rail unless Settings asks for the full sidebar; phones use the sidebar as a drawer.
  const rail = !isMobile && settings.navigation === 'rail';
  const admin = !methods.accounts || !!user?.admin;
  const openLibrary = () => navigate('library');
  const navOpen = rail || sidebarOpen;
  const viewChrome = { sidebarOpen: navOpen, onOpenSidebar: () => setSidebarOpen(true) };
  const openKeys = () => {
    if (methods.accounts) {
      setKeysReason(null);
      setKeysOpen(true);
    } else setProvidersOpen(true);
  };

  return (
    <div className={styles.app}>
      {rail ? (
        <AppRail
          view={view}
          onNavigate={navigate}
          chats={chats}
          chatsLoading={chatsLoading}
          activeChatId={activeChatId}
          onSelectChat={selectChat}
          onNewChat={newChat}
          onRenameChat={renameChat}
          onDeleteChat={deleteChat}
          documents={documents}
          user={user}
          accountsMode={!!methods.accounts}
          admin={admin}
          unreadNotices={unread}
          onOpenNotices={() => setNoticesOpen(true)}
          settingsOpen={settingsOpen}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenAccount={() => setAccountOpen(true)}
          onOpenKeys={openKeys}
          onOpenProfile={() => setProfileOpen(true)}
          onSignOut={signOut}
        />
      ) : (
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
          onSignOut={signOut}
          accountsMode={methods.accounts}
          onOpenAccount={() => setAccountOpen(true)}
          unreadNotices={unread}
          onOpenNotices={() => setNoticesOpen(true)}
          onOpenKeys={openKeys}
          onOpenSettings={() => setSettingsOpen(true)}
          documentCount={documents.length}
        />
      )}
      <div className={styles.main}>
        {/* Clouds behind every tab but Chat (which has its own rings); the pointer pushes them like wind. */}
        {view !== 'chat' && settings.tabsBackdrop !== 'off' && (
          <CloudField className={styles.clouds} dark={resolved === 'dark'} accent={settings.accent}
            still={settings.tabsBackdrop === 'still' || prefersStill(settings)} />
        )}
        {view === 'chat' && (
          <ChatView
            chat={activeChat}
            messages={messages}
            liveSteps={liveSteps}
            loadingMessages={loadingMessages}
            onRetry={retry}
            sidebarOpen={navOpen}
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
            webMode={webMode}
            onWebModeChange={setWebMode}
            freeAnswers={freeAnswers}
            onAddKey={() => { setKeysReason(null); setKeysOpen(true); }}
            accountsMode={!!methods.accounts}
          />
        )}
        {view === 'library' && (
          <LibraryView
            documents={documents}
            loading={docsLoading}
            error={docsError}
            onReload={loadDocuments}
            onUpload={upload}
            onImportUrl={importUrl}
            uploads={uploads}
            onDismissUploads={() => setUploads([])}
            onDelete={deleteDocument}
            selectedDocIds={selectedDocIds}
            onToggleDoc={toggleDoc}
            onSetSelection={setSelectedDocIds}
            onAskSelected={askSelected}
            sidebarOpen={navOpen}
            onOpenSidebar={() => setSidebarOpen(true)}
            readOnly={guest}
            hosted={!!methods.accounts}
          />
        )}
        {extractOpened && (
          <div className={styles.extract} hidden={view !== 'extract'}>
            <ExtractView
              documents={documents}
              selectedDocIds={selectedDocIds}
              sidebarOpen={navOpen}
              onOpenSidebar={() => setSidebarOpen(true)}
              onOpenLibrary={() => navigate('library')}
            />
          </div>
        )}
        {view === 'compare' && (
          <div className={styles.extract}>
            <CompareView documents={documents} sidebarOpen={navOpen} onOpenSidebar={() => setSidebarOpen(true)} />
          </div>
        )}
        {view === 'search' && (
          <SearchView documents={documents} selectedDocIds={selectedDocIds} onOpenLibrary={openLibrary} onAsk={askFromSearch} {...viewChrome} />
        )}
        {view === 'tables' && <TablesView onOpenLibrary={openLibrary} {...viewChrome} />}
        {view === 'records' && <RecordsView onOpenLibrary={openLibrary} {...viewChrome} />}
        {view === 'timeline' && <TimelineView documents={documents} onOpenLibrary={openLibrary} {...viewChrome} />}
        {view === 'privacy' && <PrivacyView documents={documents} onOpenLibrary={openLibrary} {...viewChrome} />}
        {view === 'connect' && <ConnectView accountsMode={!!methods.accounts} user={user} {...viewChrome} />}
        {view === 'admin' && (
          <AdminView user={user} accountsMode={!!methods.accounts} {...viewChrome}
            onBecameAdmin={() => api.getMe().then((u) => u && setUser(u)).catch(() => undefined)} />
        )}
        {view === 'knowledge' && (
          <div className={styles.knowledge}>
            <Suspense fallback={null}>
              <KnowledgeView
                onAskAboutEntity={askAboutEntity}
                onOpenLibrary={() => navigate('library')}
                focusEntityNames={globeFocus}
                sidebarOpen={navOpen}
                onOpenSidebar={() => setSidebarOpen(true)}
              />
            </Suspense>
          </div>
        )}
      </div>
      <AccountDialog
        key={accountOpen ? 'open' : 'closed'}
        open={accountOpen}
        methods={methods}
        onClose={() => setAccountOpen(false)}
        onSignOut={signOut}
        onDeleted={() => {
          setAccountOpen(false);
          setUser(null);
          setChats([]);
          setDocuments([]);
          toast('Your account and its data were deleted', 'good');
        }}
      />
      <KeysDialog key={keysOpen ? 'keys-open' : 'keys-closed'} open={keysOpen} reason={keysReason}
        canStoreOnServer={!!methods.accounts && user?.kind !== 'guest'}
        onClose={() => setKeysOpen(false)} onSaved={refreshFreeAnswers} />
      <NoticesDialog key={noticesOpen ? 'open' : 'closed'} open={noticesOpen} onClose={() => setNoticesOpen(false)} onRead={clearUnread} />
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        user={user}
        isMobile={isMobile}
        accountsMode={!!methods.accounts}
        freeAnswers={freeAnswers}
        onAddKey={() => { setSettingsOpen(false); setKeysReason(null); setKeysOpen(true); }}
        onOpenKeys={openKeys}
        onOpenAccount={() => setAccountOpen(true)}
        onOpenNotices={() => setNoticesOpen(true)}
        unreadNotices={unread}
        onSignOut={signOut}
        onOpenProfile={() => setProfileOpen(true)}
        onOpenAdmin={() => navigate('admin')}
        chatCount={chats.length}
        onClearChats={clearChats}
      />
      <ProvidersDialog open={providersOpen} onClose={() => setProvidersOpen(false)} />
      <Tour userKey={user?.kind === 'guest' ? 'guest' : user?.id || 'local'} />
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
