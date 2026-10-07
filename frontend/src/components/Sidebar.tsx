import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  Globe2,
  Library,
  LogIn,
  LogOut,
  MessageSquare,
  Monitor,
  Moon,
  MoreHorizontal,
  PanelLeftClose,
  Pencil,
  Search,
  Settings2,
  SquarePen,
  Sun,
  Trash2,
} from 'lucide-react';
import { api } from '../api';
import type { ChatSession, ModelInfo, User } from '../api';
import { dateGroup } from '../lib/format';
import { useTheme } from '../lib/theme';
import type { ThemePreference } from '../lib/theme';
import { Menu } from './ui/Menu';
import { useToast } from './ui/Toast';
import { BrandMark } from './BrandMark';
import styles from './Sidebar.module.css';

export type View = 'chat' | 'library' | 'knowledge';

interface SidebarProps {
  open: boolean;
  isMobile: boolean;
  onClose: () => void;
  view: View;
  onNavigate: (view: View) => void;
  chats: ChatSession[];
  chatsLoading: boolean;
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
  onRenameChat: (id: string, title: string) => void;
  onDeleteChat: (id: string) => void;
  user: User | null;
  onOpenProfile: () => void;
  onSignOut: () => void;
  documentCount: number;
}

const ICON = { size: 17, strokeWidth: 1.75 } as const;

export function Sidebar(props: SidebarProps) {
  const {
    open,
    isMobile,
    onClose,
    view,
    onNavigate,
    chats,
    chatsLoading,
    activeChatId,
    onSelectChat,
    onNewChat,
    onRenameChat,
    onDeleteChat,
    user,
    onOpenProfile,
    onSignOut,
    documentCount,
  } = props;
  const [filter, setFilter] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = q ? chats.filter((c) => (c.title || '').toLowerCase().includes(q)) : chats;
    const out: Array<{ label: string; items: ChatSession[] }> = [];
    for (const c of list) {
      const label = dateGroup(c.updated_at || c.created_at);
      const last = out[out.length - 1];
      if (last && last.label === label) last.items.push(c);
      else out.push({ label, items: [c] });
    }
    return out;
  }, [chats, filter]);

  const nav: Array<{ key: View; label: string; icon: typeof MessageSquare; hint?: string }> = [
    { key: 'chat', label: 'Chat', icon: MessageSquare },
    { key: 'library', label: 'Library', icon: Library, hint: documentCount ? String(documentCount) : undefined },
    { key: 'knowledge', label: 'Knowledge', icon: Globe2 },
  ];

  return (
    <>
      {isMobile && open && <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />}
      <aside
        className={styles.sidebar}
        data-open={open}
        data-mobile={isMobile}
        aria-label="Sidebar"
        aria-hidden={!open}
        inert={!open || undefined}
      >
        <div className={styles.top}>
          <button type="button" className={styles.brand} onClick={() => onNavigate('chat')}>
            <BrandMark size={22} />
            <span className={styles.wordmark}>OmniDoc</span>
          </button>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close sidebar" title="Close sidebar">
            <PanelLeftClose {...ICON} />
          </button>
        </div>

        <div className={styles.actions}>
          <button type="button" className={styles.newChat} onClick={onNewChat}>
            <SquarePen {...ICON} />
            <span>New chat</span>
            <span className={styles.shortcut} aria-hidden="true">
              <kbd className="kbd">⌘</kbd>
              <kbd className="kbd">⇧</kbd>
              <kbd className="kbd">O</kbd>
            </span>
          </button>
          <nav aria-label="Views">
            {nav.map(({ key, label, icon: Icon, hint }) => (
              <button
                key={key}
                type="button"
                className={styles.navItem}
                aria-current={view === key ? 'page' : undefined}
                onClick={() => onNavigate(key)}
              >
                <Icon {...ICON} />
                <span>{label}</span>
                {hint && <span className={styles.navHint}>{hint}</span>}
              </button>
            ))}
          </nav>
        </div>

        <div className={styles.recents}>
          <div className={styles.recentsHeader}>
            <span>Recents</span>
          </div>
          {chats.length > 6 && (
            <label className={styles.search}>
              <Search size={14} strokeWidth={1.75} aria-hidden="true" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search chats"
                aria-label="Search chats"
              />
            </label>
          )}
          <div className={styles.list}>
            {chatsLoading && !chats.length && (
              <div className={styles.skeletons} aria-hidden="true">
                {[72, 56, 64, 48].map((w) => (
                  <span key={w} style={{ width: `${w}%` }} />
                ))}
              </div>
            )}
            {!chatsLoading && !chats.length && <p className={styles.emptyNote}>Your conversations will appear here.</p>}
            {filter && !groups.length && <p className={styles.emptyNote}>No chats match “{filter}”.</p>}
            {groups.map((g) => (
              <section key={g.label} className={styles.group}>
                <h3 className={styles.groupLabel}>{g.label}</h3>
                <ul>
                  {g.items.map((c) => (
                    <ChatRow
                      key={c.id}
                      chat={c}
                      active={view === 'chat' && c.id === activeChatId}
                      renaming={renamingId === c.id}
                      onSelect={() => onSelectChat(c.id)}
                      onStartRename={() => setRenamingId(c.id)}
                      onRename={(title) => {
                        setRenamingId(null);
                        if (title && title !== c.title) onRenameChat(c.id, title);
                      }}
                      onDelete={() => onDeleteChat(c.id)}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>

        <SettingsFooter user={user} onOpenProfile={onOpenProfile} onSignOut={onSignOut} />
      </aside>
    </>
  );
}

interface ChatRowProps {
  chat: ChatSession;
  active: boolean;
  renaming: boolean;
  onSelect: () => void;
  onStartRename: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}

function ChatRow({ chat, active, renaming, onSelect, onStartRename, onRename, onDelete }: ChatRowProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (renaming) inputRef.current?.select();
  }, [renaming]);

  if (renaming) {
    return (
      <li className={styles.row} data-active={active}>
        <input
          ref={inputRef}
          className={styles.renameInput}
          defaultValue={chat.title}
          aria-label="Chat title"
          onBlur={(e) => onRename(e.currentTarget.value.trim())}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onRename(e.currentTarget.value.trim());
            if (e.key === 'Escape') onRename(chat.title);
          }}
        />
      </li>
    );
  }

  return (
    <li className={styles.row} data-active={active}>
      <button type="button" className={styles.rowButton} onClick={onSelect} aria-current={active ? 'true' : undefined} title={chat.title}>
        {chat.title || 'Untitled'}
      </button>
      <Menu
        label={`Actions for ${chat.title}`}
        trigger={(p) => (
          <button type="button" className={`icon-btn icon-btn-sm ${styles.rowMenu}`} aria-label="Chat actions" {...p}>
            <MoreHorizontal size={15} strokeWidth={1.75} />
          </button>
        )}
      >
        {(close) => (
          <>
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onStartRename(); }}>
              <Pencil size={15} strokeWidth={1.75} /> Rename
            </button>
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onDelete(); }}>
              <Trash2 size={15} strokeWidth={1.75} /> Delete
            </button>
          </>
        )}
      </Menu>
    </li>
  );
}

const THEMES: Array<{ key: ThemePreference; label: string; icon: typeof Sun }> = [
  { key: 'system', label: 'System', icon: Monitor },
  { key: 'light', label: 'Light', icon: Sun },
  { key: 'dark', label: 'Dark', icon: Moon },
];

function SettingsFooter({ user, onOpenProfile, onSignOut }: { user: User | null; onOpenProfile: () => void; onSignOut: () => void }) {
  const { preference, setPreference } = useTheme();
  const toast = useToast();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [current, setCurrent] = useState<string>('');
  const [modelError, setModelError] = useState<string | null>(null);

  const loadModels = () => {
    api
      .getModels()
      .then((r) => {
        setModels(r.models);
        setCurrent(r.current);
        setModelError(null);
      })
      .catch((e: Error) => setModelError(e.message));
  };

  useEffect(loadModels, []);

  const switchModel = async (name: string) => {
    try {
      const r = await api.setModel(name);
      setCurrent(r.current);
      toast(`Answers now use ${r.current}`, 'good');
    } catch (e) {
      toast((e as Error).message, 'bad');
    }
  };

  const initials = (user?.name || 'Local').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();

  return (
    <div className={styles.footer}>
      <Menu
        label="Settings"
        side="top"
        align="start"
        trigger={(p) => (
          <button type="button" className={styles.profileButton} {...p} onClick={() => { loadModels(); p.onClick(); }}>
            <span className={styles.avatar} aria-hidden="true">{initials}</span>
            <span className={styles.profileText}>
              <span className={styles.profileName}>{user?.name || 'Local profile'}</span>
              <span className={styles.profileMeta}>{current || 'Settings'}</span>
            </span>
            <Settings2 size={16} strokeWidth={1.75} className={styles.profileIcon} />
          </button>
        )}
      >
        {(close) => (
          <>
            <div className="menu-label">Appearance</div>
            {THEMES.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                type="button"
                role="menuitemradio"
                aria-checked={preference === key}
                className="menu-item"
                onClick={() => setPreference(key)}
              >
                <Icon size={15} strokeWidth={1.75} /> {label}
                {preference === key && <Check size={15} strokeWidth={2} className="menu-hint" />}
              </button>
            ))}
            <div className="menu-sep" />
            <div className="menu-label">Model</div>
            {modelError && <div className="menu-label">{modelError}</div>}
            {!models && !modelError && <div className="menu-label">Loading models…</div>}
            {models?.map((m) => (
              <button
                key={m.name}
                type="button"
                role="menuitemradio"
                aria-checked={current === m.name}
                className="menu-item"
                onClick={() => switchModel(m.name)}
              >
                <span>{m.name}</span>
                <span className="menu-hint">{current === m.name ? <Check size={15} strokeWidth={2} /> : m.parameter_size || ''}</span>
              </button>
            ))}
            <div className="menu-sep" />
            {user ? (
              <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onSignOut(); }}>
                <LogOut size={15} strokeWidth={1.75} /> Sign out of {user.email}
              </button>
            ) : (
              <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onOpenProfile(); }}>
                <LogIn size={15} strokeWidth={1.75} /> Create a local profile
              </button>
            )}
          </>
        )}
      </Menu>
    </div>
  );
}
