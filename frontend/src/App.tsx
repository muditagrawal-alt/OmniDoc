import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { AuthModal } from './components/AuthModal';
import { DocumentModal } from './components/DocumentModal';
import { api } from './api';
import type { ChatSession, ChatMessage, User } from './api';

export const App: React.FC = () => {
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const activeChatIdRef = useRef<string | null>(activeChatId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [docModalOpen, setDocModalOpen] = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);

  useEffect(() => {
    activeChatIdRef.current = activeChatId;
  }, [activeChatId]);

  // 1. Initial Load: User & Chat Sessions
  useEffect(() => {
    const initApp = async () => {
      try {
        const user = await api.getMe();
        if (user) {
          setCurrentUser(user);
        }
        const sessionChats = await api.getChats();
        setChats(sessionChats);
        if (sessionChats.length > 0) {
          setActiveChatId(sessionChats[0].id);
        }
      } catch (err) {
        console.error('Initial load error:', err);
      }
    };
    initApp();
  }, []);

  // 2. Fetch messages when activeChatId changes
  useEffect(() => {
    if (!activeChatId) {
      setMessages([]);
      return;
    }
    const loadMessages = async () => {
      try {
        const data = await api.getChat(activeChatId);
        setMessages(data.messages || []);
      } catch (err) {
        console.error('Failed to load chat messages:', err);
      }
    };
    loadMessages();
  }, [activeChatId]);

  // 3. New Chat Handler
  const handleNewChat = useCallback(async () => {
    try {
      const newChat = await api.createChat('New Conversation');
      setChats((prev) => [newChat, ...prev]);
      setActiveChatId(newChat.id);
      setMessages([]);
    } catch (err) {
      console.error('Error creating new chat:', err);
    }
  }, []);

  // Global Keyboard Shortcut: ⌘N / Ctrl+N for New Chat
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        handleNewChat();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleNewChat]);

  // 4. Select Chat Handler
  const handleSelectChat = (chatId: string) => {
    setActiveChatId(chatId);
  };

  // 5. Delete Chat Handler
  const handleDeleteChat = async (chatId: string) => {
    try {
      await api.deleteChat(chatId);
      setChats((prev) => prev.filter((c) => c.id !== chatId));
      if (activeChatId === chatId) {
        const remaining = chats.filter((c) => c.id !== chatId);
        if (remaining.length > 0) {
          setActiveChatId(remaining[0].id);
        } else {
          setActiveChatId(null);
          setMessages([]);
        }
      }
    } catch (err) {
      console.error('Error deleting chat:', err);
    }
  };

  // 6. Rename Chat Handler
  const handleRenameChat = async (chatId: string, newTitle: string) => {
    try {
      await api.renameChat(chatId, newTitle);
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, title: newTitle } : c))
      );
    } catch (err) {
      console.error('Error renaming chat:', err);
    }
  };

  // 7. Send Query Handler
  const handleSendMessage = async (queryText: string, language: string = 'en') => {
    let currentId = activeChatId;

    // If no active chat, create one first
    if (!currentId) {
      try {
        const newChat = await api.createChat(queryText.slice(0, 32));
        setChats((prev) => [newChat, ...prev]);
        setActiveChatId(newChat.id);
        currentId = newChat.id;
      } catch (err) {
        console.error('Failed to create initial chat:', err);
        return;
      }
    }

    // Optimistically append user message
    const userMsg: ChatMessage = {
      role: 'user',
      content: queryText,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const response = await api.queryChat(currentId, queryText, selectedDocIds, language);

      // Append assistant message only if user is still on this chat session
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: response.answer,
        metadata: {
          math_results: response.math_results,
          visual_artifacts: response.visual_artifacts,
          geo_locations: response.geo_locations,
          sources: response.sources,
          conflicts: response.conflicts,
          graph_entities: response.graph_entities,
          thought_process: response.thought_process,
          groundedness_score: response.groundedness_score,
        },
        timestamp: new Date().toISOString(),
      };
      if (activeChatIdRef.current === currentId) {
        setMessages((prev) => [...prev, assistantMsg]);
      }

      // Refresh chats list to capture updated title / order
      const updatedChats = await api.getChats();
      setChats(updatedChats);
    } catch (err: any) {
      console.error('Pipeline query execution failed:', err);
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: `Agentic execution error: ${err.message || 'Failed to complete reasoning.'}`,
        timestamp: new Date().toISOString(),
      };
      if (activeChatIdRef.current === currentId) {
        setMessages((prev) => [...prev, errorMsg]);
      }
    } finally {
      if (activeChatIdRef.current === currentId) {
        setLoading(false);
      }
    }
  };

  // 8. Toggle Document Filter
  const handleToggleDocSelect = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    );
  };

  // 9. Auth Handlers
  const handleLoginSuccess = (user: User) => {
    setCurrentUser(user);
    // Reload chats for this user
    api.getChats().then((data) => setChats(data));
  };

  const handleLogout = async () => {
    await api.logout();
    setCurrentUser(null);
  };

  const activeChat = chats.find((c) => c.id === activeChatId) || null;

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar Navigation */}
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
        onOpenDocuments={() => setDocModalOpen(true)}
        selectedDocCount={selectedDocIds.length}
        currentUser={currentUser}
        onOpenAuth={() => setAuthModalOpen(true)}
        onLogout={handleLogout}
      />

      {/* Main Chat Workspace */}
      <ChatArea
        chat={activeChat}
        messages={messages}
        loading={loading}
        onSendMessage={handleSendMessage}
        onOpenDocuments={() => setDocModalOpen(true)}
        selectedDocCount={selectedDocIds.length}
      />

      {/* Social Login Modal */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onSuccess={handleLoginSuccess}
      />

      {/* Document Ingestion & Knowledge Base Modal */}
      <DocumentModal
        isOpen={docModalOpen}
        onClose={() => setDocModalOpen(false)}
        selectedDocIds={selectedDocIds}
        onToggleDocSelect={handleToggleDocSelect}
      />
    </div>
  );
};

export default App;
