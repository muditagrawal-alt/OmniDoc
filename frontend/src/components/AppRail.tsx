import { useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentType, ReactNode } from 'react';
import {
  Bell, FileText, KeyRound, Library, LogIn, LogOut, MessageSquare, Plug, Search, Settings2, ShieldUser, SquarePen, UserRound,
} from 'lucide-react';
import type { ChatSession, DocumentItem, User } from '../api';
import { dateGroup } from '../lib/format';
import { isMac } from '../lib/settings';
import { BrandMark } from './BrandMark';
import { ChatRow, TOOL_VIEWS } from './Sidebar';
import type { View } from './Sidebar';
import styles from './AppRail.module.css';

type IconType = ComponentType<{ size?: number; strokeWidth?: number }>;

interface RailItemProps {
  label: string;
  icon?: IconType;
  /** Drawn instead of an icon (the avatar). */
  glyph?: ReactNode;
  active?: boolean;
  pressed?: boolean;
  onClick?: () => void;
  badge?: ReactNode;
  /** The flyout's content; without it the flyout is just the label (a tooltip). */
  children?: ReactNode;
  shortcut?: ReactNode;
  anchor?: 'top' | 'bottom';
}

/** A rail button whose flyout opens on hover or keyboard focus and stays open while the pointer is over it. */
function RailItem({ label, icon: Icon, glyph, active, pressed, onClick, badge, children, shortcut, anchor = 'top' }: RailItemProps) {
  const [open, setOpen] = useState(false);
  const timer = useRef(0);
  const schedule = (next: boolean, delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(next), delay);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <div
      className={styles.item}
      onPointerEnter={(e) => e.pointerType === 'mouse' && schedule(true, 90)}
      onPointerLeave={(e) => e.pointerType === 'mouse' && schedule(false, 200)}
      onFocus={() => {
        window.clearTimeout(timer.current);
        setOpen(true);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button type="button" className={styles.button} aria-label={label} aria-current={active ? 'page' : undefined}
        aria-pressed={pressed} onClick={() => {
          onClick?.();
          if (!children) setOpen(false);
        }}>
        {glyph ?? (Icon && <Icon size={19} strokeWidth={1.75} />)}
        {badge}
      </button>
      <div className={styles.flyout} data-open={open || undefined} data-anchor={anchor} data-tip={!children || undefined}
        role={children ? 'region' : undefined} aria-label={children ? label : undefined} aria-hidden={children ? undefined : true}>
        {children ?? (
          <span className={styles.tip}>
            {label}
            {shortcut && <span className={styles.keys}>{shortcut}</span>}
          </span>
        )}
      </div>
    </div>
  );
}

function ChatsFlyout({ chats, loading, activeChatId, view, onSelectChat, onNewChat, onRenameChat, onDeleteChat }: {
  chats: ChatSession[]; loading: boolean; activeChatId: string | null; view: View;
  onSelectChat: (id: string) => void; onNewChat: () => void;
  onRenameChat: (id: string, title: string) => void; onDeleteChat: (id: string) => void;
}) {
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

  return (
    <div className={styles.panel}>
      <div className={styles.panelHead}>
        <strong>Chats</strong>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onNewChat}>
          <SquarePen size={14} strokeWidth={1.75} /> New
        </button>
      </div>
      {chats.length > 4 && (
        <label className={styles.search}>
          <Search size={14} strokeWidth={1.75} aria-hidden="true" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search chats" aria-label="Search chats" />
        </label>
      )}
      <div className={styles.scroll}>
        {loading && !chats.length && <p className={styles.empty}>Loading…</p>}
        {!loading && !chats.length && <p className={styles.empty}>Your conversations will appear here.</p>}
        {filter && !groups.length && <p className={styles.empty}>No chats match “{filter}”.</p>}
        {groups.map((g) => (
          <section key={g.label}>
            <h4 className={styles.groupLabel}>{g.label}</h4>
            <ul className={styles.rows}>
              {g.items.map((c) => (
                <ChatRow key={c.id} chat={c} active={view === 'chat' && c.id === activeChatId} renaming={renamingId === c.id}
                  onSelect={() => onSelectChat(c.id)} onStartRename={() => setRenamingId(c.id)}
                  onRename={(title) => {
                    setRenamingId(null);
                    if (title && title !== c.title) onRenameChat(c.id, title);
                  }}
                  onDelete={() => onDeleteChat(c.id)} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function LibraryFlyout({ documents, onOpen }: { documents: DocumentItem[]; onOpen: () => void }) {
  const recent = [...documents].sort((a, b) => (b.upload_date || '').localeCompare(a.upload_date || '')).slice(0, 6);
  return (
    <div className={styles.panel}>
      <div className={styles.panelHead}>
        <strong>Library</strong>
        <span className={styles.count}>{documents.length} {documents.length === 1 ? 'document' : 'documents'}</span>
      </div>
      {recent.length ? (
        <ul className={styles.docs}>
          {recent.map((d) => (
            <li key={d.id}>
              <button type="button" onClick={onOpen} title={d.filename}>
                <FileText size={14} strokeWidth={1.75} />
                <span>{d.filename}</span>
                {d.pages ? <small>{d.pages} p.</small> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>No documents yet. Add PDFs, scans, slides or recordings in the library.</p>
      )}
      <button type="button" className={`btn btn-secondary btn-sm ${styles.open}`} onClick={onOpen}>Open the library</button>
    </div>
  );
}

function ToolFlyout({ title, text }: { title: string; text: string }) {
  return (
    <div className={`${styles.panel} ${styles.tool}`}>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

interface AppRailProps {
  view: View;
  onNavigate: (view: View) => void;
  chats: ChatSession[];
  chatsLoading: boolean;
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
  onRenameChat: (id: string, title: string) => void;
  onDeleteChat: (id: string) => void;
  documents: DocumentItem[];
  user: User | null;
  accountsMode: boolean;
  /** Shows the Admin tab (an administrator, or anyone on a local install). */
  admin: boolean;
  unreadNotices: number;
  onOpenNotices: () => void;
  settingsOpen: boolean;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
  onOpenKeys: () => void;
  onOpenProfile: () => void;
  onSignOut: () => void;
}

/** Desktop navigation: a narrow rail of icons, each with a flyout of its own (chats, library, account). */
export function AppRail(props: AppRailProps) {
  const { view, onNavigate, user, accountsMode, documents } = props;
  const mod = isMac ? '⌘' : 'Ctrl';
  const guest = user?.kind === 'guest';
  const initials = (user?.name || 'Local').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();

  return (
    <nav className={styles.rail} aria-label="Main">
      <button type="button" className={styles.brand} onClick={() => onNavigate('chat')} aria-label="OmniDoc, go to chat">
        <BrandMark size={24} />
      </button>

      <div className={styles.group}>
        <RailItem label="New chat" icon={SquarePen} onClick={props.onNewChat}
          shortcut={<><kbd className="kbd">{mod}</kbd><kbd className="kbd">⇧</kbd><kbd className="kbd">O</kbd></>} />
        <RailItem label="Chat" icon={MessageSquare} active={view === 'chat'} onClick={() => onNavigate('chat')}>
          <ChatsFlyout chats={props.chats} loading={props.chatsLoading} activeChatId={props.activeChatId} view={view}
            onSelectChat={props.onSelectChat} onNewChat={props.onNewChat} onRenameChat={props.onRenameChat}
            onDeleteChat={props.onDeleteChat} />
        </RailItem>
        <RailItem label="Search" icon={Search} active={view === 'search'} onClick={() => onNavigate('search')}
          shortcut={<><kbd className="kbd">{mod}</kbd><kbd className="kbd">K</kbd></>} />
        <RailItem label="Library" icon={Library} active={view === 'library'} onClick={() => onNavigate('library')}
          badge={documents.length ? <span className={styles.count}>{documents.length}</span> : null}>
          <LibraryFlyout documents={documents} onOpen={() => onNavigate('library')} />
        </RailItem>
      </div>

      <div className={styles.group} role="group" aria-label="Tools">
        {TOOL_VIEWS.map((t) => (
          <RailItem key={t.key} label={t.label} icon={t.icon} active={view === t.key} onClick={() => onNavigate(t.key)}>
            <ToolFlyout title={t.label} text={t.about} />
          </RailItem>
        ))}
      </div>

      <div className={`${styles.group} ${styles.bottom}`}>
        <RailItem label="Connect" icon={Plug} active={view === 'connect'} onClick={() => onNavigate('connect')}>
          <ToolFlyout title="Connect" text="Use your library from Claude Code, Claude Desktop or Cursor through OmniDoc's MCP server." />
        </RailItem>
        {props.admin && (
          <RailItem label="Admin" icon={ShieldUser} active={view === 'admin'} onClick={() => onNavigate('admin')}>
            <ToolFlyout title="Admin" text="Usage, server health and memory, the default model for everyone, and announcements." />
          </RailItem>
        )}
        {accountsMode && user && !guest && (
          <RailItem label="Notifications" icon={Bell} onClick={props.onOpenNotices}
            badge={props.unreadNotices > 0 ? <span className={styles.dot} aria-label={`${props.unreadNotices} new`} /> : null} />
        )}
        <RailItem label="Settings" icon={Settings2} pressed={props.settingsOpen} onClick={props.onOpenSettings}
          shortcut={<><kbd className="kbd">{mod}</kbd><kbd className="kbd">,</kbd></>} />
        <RailItem label={user?.name || 'Profile'} glyph={<span className={styles.avatar} aria-hidden="true">{initials}</span>} anchor="bottom">
          <div className={styles.panel}>
            <div className={styles.account}>
              <span className={styles.avatarLarge} aria-hidden="true">{initials}</span>
              <div>
                <strong>{user?.name || 'Local profile'}</strong>
                <span>{guest ? 'Exploring the demo, read-only' : user?.email || (accountsMode ? 'Signed in' : 'This computer')}</span>
              </div>
            </div>
            {guest && (
              <p className={styles.note}>A shared sample library. Sign in to upload your own documents.</p>
            )}
            <div className={styles.menu}>
              {accountsMode && user && (
                <button type="button" className="menu-item" onClick={props.onOpenAccount}>
                  <UserRound size={15} strokeWidth={1.75} /> {guest ? 'About the demo' : 'Account and security'}
                </button>
              )}
              <button type="button" className="menu-item" onClick={props.onOpenKeys}>
                <KeyRound size={15} strokeWidth={1.75} /> {accountsMode ? 'Your own model key' : 'Free model APIs'}
              </button>
              <button type="button" className="menu-item" onClick={props.onOpenSettings}>
                <Settings2 size={15} strokeWidth={1.75} /> Settings
              </button>
              {user ? (
                <button type="button" className="menu-item" onClick={props.onSignOut}>
                  <LogOut size={15} strokeWidth={1.75} /> {guest ? 'Leave the demo and sign in' : 'Sign out'}
                </button>
              ) : (
                <button type="button" className="menu-item" onClick={props.onOpenProfile}>
                  <LogIn size={15} strokeWidth={1.75} /> Create a local profile
                </button>
              )}
            </div>
          </div>
        </RailItem>
      </div>
    </nav>
  );
}
