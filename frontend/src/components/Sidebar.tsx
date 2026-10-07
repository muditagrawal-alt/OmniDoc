import React, { useState } from 'react';
import {
  Plus,
  MessageSquare,
  Search,
  Layers,
  Trash2,
  Edit2,
  Check,
  X,
  LogOut,
  User as UserIcon,
  ChevronRight,
  Sparkles
} from 'lucide-react';
import type { ChatSession, User } from '../api';

interface SidebarProps {
  chats: ChatSession[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
  onRenameChat: (chatId: string, newTitle: string) => void;
  onOpenDocuments: () => void;
  selectedDocCount: number;
  currentUser: User | null;
  onOpenAuth: () => void;
  onLogout: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  onOpenDocuments,
  selectedDocCount,
  currentUser,
  onOpenAuth,
  onLogout,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  // Chronological grouping helper
  const groupChats = (chatList: ChatSession[]) => {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const yesterday = today - 86400000;
    const past7Days = today - 7 * 86400000;

    const groups: { [key: string]: ChatSession[] } = {
      Today: [],
      Yesterday: [],
      'Previous 7 Days': [],
      Older: [],
    };

    chatList.forEach((c) => {
      const chatTime = new Date(c.updated_at || c.created_at).getTime();
      if (chatTime >= today) {
        groups.Today.push(c);
      } else if (chatTime >= yesterday) {
        groups.Yesterday.push(c);
      } else if (chatTime >= past7Days) {
        groups['Previous 7 Days'].push(c);
      } else {
        groups.Older.push(c);
      }
    });

    return groups;
  };

  const filteredChats = chats.filter((c) =>
    (c.title || 'New Conversation').toLowerCase().includes(searchQuery.toLowerCase())
  );

  const grouped = groupChats(filteredChats);

  const startEditing = (chat: ChatSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(chat.id);
    setEditTitle(chat.title || 'New Conversation');
  };

  const saveEditing = (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (editTitle.trim()) {
      onRenameChat(chatId, editTitle.trim());
    }
    setEditingId(null);
  };

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
  };

  return (
    <aside style={{
      width: '270px',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: 'var(--bg-sidebar)',
      borderRight: '1px solid var(--border-subtle)',
      flexShrink: 0,
      userSelect: 'none',
    }}>
      {/* Top Brand Header */}
      <div style={{
        padding: '1.1rem 1.15rem 0.85rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '9px',
            background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            boxShadow: '0 2px 8px rgba(59, 130, 246, 0.35)',
          }}>
            <Sparkles size={18} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '1rem', letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
              OmniDoc
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', fontWeight: 500 }}>
              Agentic Graph RAG
            </div>
          </div>
        </div>

        <span style={{
          fontSize: '0.68rem',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          color: '#93c5fd',
          padding: '0.15rem 0.45rem',
          borderRadius: 'var(--radius-full)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          fontWeight: 600,
        }}>
          Qwen 2.5
        </span>
      </div>

      {/* Action Buttons: New Chat & Document Library */}
      <div style={{ padding: '0.85rem 1rem 0.4rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <button
          onClick={onNewChat}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '0.65rem 0.85rem',
            backgroundColor: 'var(--accent-primary)',
            borderRadius: 'var(--radius-md)',
            color: '#ffffff',
            fontWeight: 500,
            fontSize: '0.86rem',
            boxShadow: '0 2px 8px rgba(59, 130, 246, 0.25)',
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--accent-primary-hover)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'var(--accent-primary)'}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Plus size={16} />
            <span>New Chat</span>
          </div>
          <span style={{ fontSize: '0.7rem', opacity: 0.8, backgroundColor: 'rgba(0,0,0,0.2)', padding: '0.1rem 0.35rem', borderRadius: 'var(--radius-sm)' }}>
            ⌘N
          </span>
        </button>

        <button
          onClick={onOpenDocuments}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '0.55rem 0.85rem',
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-secondary)',
            fontSize: '0.82rem',
            fontWeight: 500,
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface-elevated)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface)'}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Layers size={14} style={{ color: 'var(--accent-primary)' }} />
            <span>Document Library</span>
          </div>
          {selectedDocCount > 0 && (
            <span style={{
              fontSize: '0.68rem',
              backgroundColor: 'var(--accent-primary)',
              color: '#fff',
              padding: '0.1rem 0.4rem',
              borderRadius: 'var(--radius-full)',
              fontWeight: 600,
            }}>
              {selectedDocCount} active
            </span>
          )}
        </button>
      </div>

      {/* Search Input */}
      <div style={{ padding: '0.4rem 1rem 0.6rem' }}>
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{
            position: 'absolute',
            left: '0.65rem',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--text-dim)'
          }} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
            style={{
              width: '100%',
              padding: '0.42rem 0.5rem 0.42rem 1.85rem',
              fontSize: '0.78rem',
              borderRadius: 'var(--radius-sm)',
            }}
          />
        </div>
      </div>

      {/* Chat History List */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '0.25rem 0.65rem 1rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.85rem',
      }}>
        {Object.entries(grouped).map(([groupTitle, groupItems]) => {
          if (groupItems.length === 0) return null;
          return (
            <div key={groupTitle}>
              <div style={{
                fontSize: '0.7rem',
                fontWeight: 600,
                color: 'var(--text-dim)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                padding: '0.2rem 0.5rem 0.4rem',
              }}>
                {groupTitle}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                {groupItems.map((chat) => {
                  const isActive = chat.id === activeChatId;
                  const isEditing = chat.id === editingId;

                  return (
                    <div
                      key={chat.id}
                      onClick={() => !isEditing && onSelectChat(chat.id)}
                      style={{
                        position: 'relative',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.45rem 0.65rem',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: isActive ? 'var(--bg-surface-elevated)' : 'transparent',
                        color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                        cursor: 'pointer',
                        transition: 'var(--transition-fast)',
                        border: `1px solid ${isActive ? 'var(--border-medium)' : 'transparent'}`,
                      }}
                      onMouseEnter={(e) => {
                        if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
                      }}
                      onMouseLeave={(e) => {
                        if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, overflow: 'hidden' }}>
                        <MessageSquare size={14} style={{ color: isActive ? 'var(--accent-primary)' : 'var(--text-dim)', flexShrink: 0 }} />
                        {isEditing ? (
                          <input
                            type="text"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            autoFocus
                            style={{
                              fontSize: '0.8rem',
                              padding: '0.15rem 0.35rem',
                              width: '100%',
                              borderRadius: 'var(--radius-sm)',
                            }}
                          />
                        ) : (
                          <span style={{
                            fontSize: '0.82rem',
                            fontWeight: isActive ? 500 : 400,
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}>
                            {chat.title || 'New Conversation'}
                          </span>
                        )}
                      </div>

                      {/* Item Actions */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', marginLeft: '0.25rem' }}>
                        {isEditing ? (
                          <>
                            <button onClick={(e) => saveEditing(chat.id, e)} style={{ padding: '0.2rem', color: 'var(--accent-emerald)' }}>
                              <Check size={13} />
                            </button>
                            <button onClick={cancelEditing} style={{ padding: '0.2rem', color: 'var(--text-dim)' }}>
                              <X size={13} />
                            </button>
                          </>
                        ) : isActive && (
                          <>
                            <button
                              onClick={(e) => startEditing(chat, e)}
                              title="Rename chat"
                              style={{ padding: '0.2rem', color: 'var(--text-dim)' }}
                              onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
                              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
                            >
                              <Edit2 size={12} />
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteChat(chat.id);
                              }}
                              title="Delete chat"
                              style={{ padding: '0.2rem', color: 'var(--text-dim)' }}
                              onMouseEnter={(e) => e.currentTarget.style.color = 'var(--accent-rose)'}
                              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
                            >
                              <Trash2 size={12} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {chats.length === 0 && (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: '0.78rem', padding: '2rem 1rem' }}>
            No chat history yet.<br />Start a new conversation!
          </div>
        )}
      </div>

      {/* User Profile Footer */}
      <div style={{
        padding: '0.85rem 1rem',
        borderTop: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-app)',
      }}>
        {currentUser ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', overflow: 'hidden' }}>
              <img
                src={currentUser.avatar_url || 'https://api.dicebear.com/7.x/identicon/svg?seed=user'}
                alt={currentUser.name}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-medium)',
                  flexShrink: 0
                }}
              />
              <div style={{ overflow: 'hidden' }}>
                <div style={{
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis'
                }}>
                  {currentUser.name}
                </div>
                <div style={{
                  fontSize: '0.7rem',
                  color: 'var(--text-dim)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem'
                }}>
                  <span style={{ textTransform: 'capitalize' }}>{currentUser.provider}</span>
                </div>
              </div>
            </div>

            <button
              onClick={onLogout}
              title="Sign out"
              style={{
                color: 'var(--text-dim)',
                padding: '0.35rem',
                borderRadius: 'var(--radius-sm)'
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = 'var(--accent-rose)'}
              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
            >
              <LogOut size={15} />
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenAuth}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              width: '100%',
              padding: '0.6rem 0.85rem',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-medium)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-primary)',
              fontSize: '0.82rem',
              fontWeight: 500,
            }}
            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface-elevated)'}
            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface)'}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <UserIcon size={15} style={{ color: 'var(--accent-primary)' }} />
              <span>Sign In / Log In</span>
            </div>
            <ChevronRight size={14} style={{ color: 'var(--text-dim)' }} />
          </button>
        )}
      </div>
    </aside>
  );
};
