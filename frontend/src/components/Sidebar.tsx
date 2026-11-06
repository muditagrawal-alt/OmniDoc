import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bell,
  KeyRound,
  GitCompareArrows,
  CalendarRange,
  FileCheck2,
  Globe2,
  Library,
  ListChecks,
  Plug,
  ShieldCheck,
  ShieldUser,
  Table2,
  LogIn,
  LogOut,
  UserRound,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  Pencil,
  Search,
  Settings2,
  Sparkles,
  SquarePen,
  Trash2,
} from 'lucide-react';
import type { ChatSession, User } from '../api';
import { dateGroup } from '../lib/format';
import { modelName, useModels } from '../lib/models';
import { useSettings } from '../lib/settings';
import { Menu } from './ui/Menu';
import { BrandMark } from './BrandMark';
import styles from './Sidebar.module.css';

export type View =
  | 'chat' | 'search' | 'library' | 'extract' | 'compare' | 'tables' | 'records' | 'timeline' | 'privacy' | 'knowledge'
  | 'connect' | 'admin';

/** The tools beside Chat: label, icon and a sentence for the rail's flyout. */
export const TOOL_VIEWS: Array<{ key: View; label: string; icon: typeof MessageSquare; about: string }> = [
  { key: 'extract', label: 'Extract', icon: ListChecks, about: 'Pull invoice numbers, totals, dates or any field you name from many documents into one table, each value with its citation.' },
  { key: 'compare', label: 'Compare', icon: GitCompareArrows, about: 'Two drafts or two years side by side: changed clauses, added sections and moved figures.' },
  { key: 'tables', label: 'Tables', icon: Table2, about: 'Every table found in your documents, as data: open it as a grid, download it as CSV.' },
  { key: 'records', label: 'Records', icon: FileCheck2, about: 'Invoices, receipts and contracts recognised, their key fields read and checked against each other.' },
  { key: 'timeline', label: 'Timeline', icon: CalendarRange, about: 'Every date in the library in order: deadlines, filings, effective dates, each linked to its page.' },
  { key: 'privacy', label: 'Privacy scan', icon: ShieldCheck, about: 'Find Aadhaar, PAN, GSTIN, card and phone numbers across the library, and download redacted copies.' },
  { key: 'knowledge', label: 'Knowledge', icon: Globe2, about: 'People, companies, places and amounts linked across your library, on a globe you can search.' },
];

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
  /** A hosted server with accounts: the menu opens the account dialog instead of local profiles. */
  accountsMode?: boolean;
  onOpenAccount?: () => void;
  /** Unread security notices and announcements (accounts only). */
  unreadNotices?: number;
  onOpenNotices?: () => void;
  /** Opens "Your own model key" (bring your own free key after the free answers). */
  onOpenKeys?: () => void;
  onOpenSettings?: () => void;
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
    accountsMode = false,
    onOpenAccount,
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

  const admin = !accountsMode || !!user?.admin;
  const nav: Array<{ key: View; label: string; icon: typeof MessageSquare; hint?: string }> = [
    { key: 'chat', label: 'Chat', icon: MessageSquare },
    { key: 'search', label: 'Search', icon: Search },
    { key: 'library', label: 'Library', icon: Library, hint: documentCount ? String(documentCount) : undefined },
    ...TOOL_VIEWS.map(({ key, label, icon }) => ({ key, label, icon })),
    { key: 'connect', label: 'Connect', icon: Plug },
    ...(admin ? [{ key: 'admin' as View, label: 'Admin', icon: ShieldUser }] : []),
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

        {user?.kind === 'guest' && (
          <div className={styles.demoCard}>
            <strong>You are exploring the demo</strong>
            <span>A shared, read-only sample library. Sign in to upload your own documents.</span>
            <button type="button" className="btn btn-primary btn-sm" onClick={onSignOut}>Sign in</button>
          </div>
        )}
        <SettingsFooter user={user} onOpenProfile={onOpenProfile} onSignOut={onSignOut} accountsMode={accountsMode}
          onOpenAccount={onOpenAccount} unreadNotices={props.unreadNotices ?? 0} onOpenNotices={props.onOpenNotices}
          onOpenKeys={props.onOpenKeys} onOpenSettings={props.onOpenSettings} />
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

export function ChatRow({ chat, active, renaming, onSelect, onStartRename, onRename, onDelete }: ChatRowProps) {
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

function SettingsFooter({ user, onOpenProfile, onSignOut, accountsMode = false, onOpenAccount, unreadNotices = 0, onOpenNotices, onOpenKeys, onOpenSettings }: {
  user: User | null; onOpenProfile: () => void; onSignOut: () => void; accountsMode?: boolean; onOpenAccount?: () => void;
  unreadNotices?: number; onOpenNotices?: () => void; onOpenKeys?: () => void; onOpenSettings?: () => void;
}) {
  const { models, current } = useModels();
  const { model: mine } = useSettings();
  const initials = (user?.name || 'Local').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();

  return (
    <div className={styles.footer}>
      <Menu
        label="Account"
        side="top"
        align="start"
        trigger={(p) => (
          <button type="button" className={styles.profileButton} {...p}>
            <span className={styles.avatar} aria-hidden="true" data-unread={unreadNotices > 0 || undefined}>{initials}</span>
            <span className={styles.profileText}>
              <span className={styles.profileName}>{user?.name || 'Local profile'}</span>
              <span className={styles.profileMeta}>{mine || current ? modelName(mine || current, models) : 'Settings'}</span>
            </span>
            <Settings2 size={16} strokeWidth={1.75} className={styles.profileIcon} />
          </button>
        )}
      >
        {(close) => (
          <>
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onOpenSettings?.(); }}>
              <Settings2 size={15} strokeWidth={1.75} /> Settings…
            </button>
            <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onOpenKeys?.(); }}>
              {accountsMode ? <KeyRound size={15} strokeWidth={1.75} /> : <Sparkles size={15} strokeWidth={1.75} />}
              {accountsMode ? 'Your own model key…' : 'Free model APIs and web search…'}
            </button>
            <div className="menu-sep" />
            {accountsMode && (
              <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onOpenAccount?.(); }}>
                <UserRound size={15} strokeWidth={1.75} /> {user?.kind === 'guest' ? 'About the demo…' : 'Account and security…'}
              </button>
            )}
            {accountsMode && user?.kind !== 'guest' && (
              <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onOpenNotices?.(); }}>
                <Bell size={15} strokeWidth={1.75} /> Notifications
                {unreadNotices > 0 && <span className="menu-hint">{unreadNotices} new</span>}
              </button>
            )}
            {user ? (
              <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); onSignOut(); }}>
                <LogOut size={15} strokeWidth={1.75} /> {user.kind === 'guest' ? 'Leave the demo' : `Sign out of ${user.email || user.name}`}
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
