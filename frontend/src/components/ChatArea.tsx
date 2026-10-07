import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Sparkles,
  FileDown,
  FileText,
  Layers,
  ChevronDown,
  RefreshCw,
  TrendingUp,
  GitFork,
  Calculator,
  ShieldCheck,
  Zap,
  Mic,
  MicOff,
  Paperclip,
  Share2,
  MessageSquare,
  CheckCircle2
} from 'lucide-react';
import { api } from '../api';
import type { ChatMessage, ChatSession } from '../api';
import { ChatMessageItem } from './ChatMessageItem';
import { LanguageSelector } from './LanguageSelector';
import { KnowledgeGraphView } from './KnowledgeGraphView';
import { AudioWaveVisualizer } from './AudioWaveVisualizer';
import { voiceController } from '../utils/voice';

interface ChatAreaProps {
  chat: ChatSession | null;
  messages: ChatMessage[];
  loading: boolean;
  onSendMessage: (query: string, language?: string) => void;
  onOpenDocuments: () => void;
  selectedDocCount: number;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  chat,
  messages,
  loading,
  onSendMessage,
  onOpenDocuments,
  selectedDocCount,
}) => {
  const [activeTab, setActiveTab] = useState<'chat' | 'graph'>('chat');
  const [inputQuery, setInputQuery] = useState('');
  const [language, setLanguage] = useState('en');
  const [isListening, setIsListening] = useState(false);
  const [voiceInputUsed, setVoiceInputUsed] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null);
  const [uploadingJit, setUploadingJit] = useState(false);
  const [lastUploadedDoc, setLastUploadedDoc] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // When assistant finishes answering after voice input was used, auto-read response
  useEffect(() => {
    if (voiceInputUsed && messages.length > 0 && !loading) {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg.role === 'assistant') {
        voiceController.setLanguage(language);
        voiceController.speak(lastMsg.content);
        setVoiceInputUsed(false);
      }
    }
  }, [messages, loading, voiceInputUsed, language]);

  const handleLanguageChange = (code: string) => {
    setLanguage(code);
    voiceController.setLanguage(code);
  };

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputQuery.trim() || loading) return;
    const query = inputQuery.trim();
    setInputQuery('');
    onSendMessage(query, language);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Voice Input Toggle
  const toggleVoiceInput = () => {
    if (isListening) {
      voiceController.stopListening();
      setIsListening(false);
    } else {
      voiceController.setLanguage(language);
      setIsListening(true);
      voiceController.startListening(
        (transcript, isFinal) => {
          setInputQuery(transcript);
          if (isFinal && transcript.trim().length > 3) {
            setIsListening(false);
            setVoiceInputUsed(true);
          }
        },
        (err) => {
          console.warn('Speech error:', err);
          setIsListening(false);
        },
        () => {
          setIsListening(false);
        }
      );
    }
  };

  // JIT File Upload
  const handleJitUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadingJit(true);
    try {
      const res = await api.uploadDocument(file);
      setLastUploadedDoc(`${file.name} (${res.chunk_count} chunks)`);
      setTimeout(() => setLastUploadedDoc(null), 5000);
    } catch (err) {
      console.error('JIT upload error:', err);
    } finally {
      setUploadingJit(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleExportFullChat = async (type: 'pdf' | 'docx') => {
    if (!chat) return;
    setExporting(type);
    setExportOpen(false);
    try {
      const blob = type === 'pdf'
        ? await api.exportPdf(chat.id, undefined, chat.title)
        : await api.exportDocx(chat.id, undefined, chat.title);

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(chat.title || 'OmniDoc_Analysis').replace(/\s+/g, '_')}.${type}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export error:', err);
    } finally {
      setExporting(null);
    }
  };

  const samplePrompts = [
    {
      title: 'Compare Gross Margins',
      desc: 'Calculate growth between FY2023 & FY2024 with verified math',
      icon: <Calculator size={16} style={{ color: 'var(--accent-primary)' }} />,
      query: 'Compare the gross margin expansion from 2023 to 2024 and calculate the percentage increase.'
    },
    {
      title: 'Traverse Knowledge Graph',
      desc: 'Inspect multi-hop entity relationships and company hierarchy',
      icon: <GitFork size={16} style={{ color: 'var(--accent-violet)' }} />,
      query: 'Explore the entity relations connecting corporate officers, revenue drivers, and primary risk factors.'
    },
    {
      title: 'Audit Multi-Doc Conflicts',
      desc: 'Detect contradictory claims between 10-K, 10-Q, and filings',
      icon: <ShieldCheck size={16} style={{ color: 'var(--accent-amber)' }} />,
      query: 'Audit all conflicting revenue numbers or guidance targets between the reported filings.'
    },
    {
      title: 'Calculate 3-Year CAGR',
      desc: 'Run deterministic SymPy formula with step-by-step proofs',
      icon: <TrendingUp size={16} style={{ color: 'var(--accent-emerald)' }} />,
      query: 'Compute the 3-year Compound Annual Growth Rate (CAGR) for net cloud revenues.'
    }
  ];

  return (
    <main style={{
      flex: 1,
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: '#090b0e',
      overflow: 'hidden',
      position: 'relative'
    }}>
      {/* Top Header Bar */}
      <header style={{
        height: '56px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 1.5rem',
        borderBottom: '1px solid var(--border-subtle)',
        backgroundColor: 'rgba(9, 11, 14, 0.85)',
        backdropFilter: 'blur(8px)',
        zIndex: 10
      }}>
        {/* Left: Tab Switcher (Chat vs Knowledge Graph) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '2px',
          }}>
            <button
              onClick={() => setActiveTab('chat')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.3rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.78rem',
                fontWeight: 500,
                backgroundColor: activeTab === 'chat' ? 'var(--bg-surface-elevated)' : 'transparent',
                color: activeTab === 'chat' ? 'var(--text-primary)' : 'var(--text-muted)',
              }}
            >
              <MessageSquare size={13} style={{ color: activeTab === 'chat' ? 'var(--accent-primary)' : 'inherit' }} />
              <span>Chat & Reasoning</span>
            </button>

            <button
              onClick={() => setActiveTab('graph')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.3rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.78rem',
                fontWeight: 500,
                backgroundColor: activeTab === 'graph' ? 'var(--bg-surface-elevated)' : 'transparent',
                color: activeTab === 'graph' ? 'var(--text-primary)' : 'var(--text-muted)',
              }}
            >
              <Share2 size={13} style={{ color: activeTab === 'graph' ? 'var(--accent-primary)' : 'inherit' }} />
              <span>Interactive Knowledge Graph</span>
            </button>
          </div>

          {/* Document Scope Pill */}
          {activeTab === 'chat' && (
            <button
              onClick={onOpenDocuments}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                fontSize: '0.74rem',
                padding: '0.25rem 0.55rem',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--bg-surface-elevated)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-secondary)'
              }}
            >
              <Layers size={12} style={{ color: 'var(--accent-primary)' }} />
              <span>{selectedDocCount > 0 ? `${selectedDocCount} docs active` : 'All Documents'}</span>
            </button>
          )}
        </div>

        {/* Right: Multi-Lingual Selector, Local Engine Pill & Publication Export */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          {/* Indian Multi-Lingual Language Picker */}
          <LanguageSelector
            currentLanguage={language}
            onChangeLanguage={handleLanguageChange}
          />

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            fontSize: '0.74rem',
            color: 'var(--text-dim)',
            padding: '0.25rem 0.55rem',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--bg-surface)'
          }}>
            <Zap size={12} style={{ color: 'var(--accent-emerald)' }} />
            <span>Local Metal Qwen 2.5</span>
          </div>

          {/* Export Dropdown Button */}
          {activeTab === 'chat' && messages.length > 0 && (
            <div style={{ position: 'relative' }}>
              <button
                onClick={() => setExportOpen(!exportOpen)}
                disabled={exporting !== null}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  padding: '0.35rem 0.7rem',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-medium)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.78rem',
                  fontWeight: 500,
                  color: 'var(--text-primary)'
                }}
              >
                <FileDown size={13} style={{ color: 'var(--accent-primary)' }} />
                <span>{exporting ? `Compiling...` : 'Export Publication'}</span>
                <ChevronDown size={12} />
              </button>

              {exportOpen && (
                <div style={{
                  position: 'absolute',
                  right: 0,
                  top: '110%',
                  width: '240px',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-medium)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: 'var(--shadow-lg)',
                  padding: '0.4rem',
                  zIndex: 100,
                  animation: 'fadeIn 0.15s ease-out'
                }}>
                  <button
                    onClick={() => handleExportFullChat('pdf')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.65rem',
                      width: '100%',
                      padding: '0.6rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8rem',
                      color: 'var(--text-primary)',
                      textAlign: 'left'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <FileDown size={16} style={{ color: '#ef4444' }} />
                    <div>
                      <div style={{ fontWeight: 500 }}>Export Executive PDF</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>WeasyPrint CSS3 Paged Media</div>
                    </div>
                  </button>

                  <button
                    onClick={() => handleExportFullChat('docx')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.65rem',
                      width: '100%',
                      padding: '0.6rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8rem',
                      color: 'var(--text-primary)',
                      textAlign: 'left'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <FileText size={16} style={{ color: '#3b82f6' }} />
                    <div>
                      <div style={{ fontWeight: 500 }}>Export Word DOCX</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Native Microsoft Word format</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Main Tab View: Knowledge Graph View OR Chat Area */}
      {activeTab === 'graph' ? (
        <KnowledgeGraphView
          onStartChatWithEntity={(entityName) => {
            setActiveTab('chat');
            onSendMessage(`Analyze ${entityName} and summarize its key relationships and financial metrics.`, language);
          }}
        />
      ) : (
        <>
          {/* Message Feed / Hero Launchpad */}
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
            {messages.length === 0 ? (
              <div style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '2rem 1.5rem',
                maxWidth: '760px',
                margin: '0 auto',
                width: '100%'
              }}>
                <div style={{
                  width: '52px',
                  height: '52px',
                  borderRadius: '16px',
                  background: 'linear-gradient(135deg, #3b82f6 0%, #1e40af 100%)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#ffffff',
                  marginBottom: '1.25rem',
                  boxShadow: '0 4px 20px rgba(59, 130, 246, 0.35)'
                }}>
                  <Sparkles size={26} />
                </div>

                <h2 style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.35rem', textAlign: 'center' }}>
                  What shall we investigate today?
                </h2>
                <p style={{ fontSize: '0.88rem', color: 'var(--text-muted)', textAlign: 'center', maxWidth: '520px', marginBottom: '2rem' }}>
                  Ask questions with text or voice in English, Hindi, Marathi, Tamil, Telugu, and more.
                </p>

                {/* Quick Prompt Cards */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                  gap: '0.85rem',
                  width: '100%'
                }}>
                  {samplePrompts.map((p, idx) => (
                    <div
                      key={idx}
                      onClick={() => onSendMessage(p.query, language)}
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-lg)',
                        padding: '1rem',
                        cursor: 'pointer',
                        transition: 'var(--transition-fast)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.4rem'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--bg-surface-elevated)';
                        e.currentTarget.style.borderColor = 'var(--border-medium)';
                        e.currentTarget.style.transform = 'translateY(-2px)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--bg-surface)';
                        e.currentTarget.style.borderColor = 'var(--border-subtle)';
                        e.currentTarget.style.transform = 'translateY(0)';
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {p.icon}
                        <span style={{ fontWeight: 600, fontSize: '0.86rem', color: 'var(--text-primary)' }}>
                          {p.title}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                        {p.desc}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ maxWidth: '860px', width: '100%', margin: '0 auto', display: 'flex', flexDirection: 'column' }}>
                {messages.map((m, idx) => (
                  <ChatMessageItem key={m.id ? `msg-id-${m.id}` : `msg-temp-${idx}-${m.timestamp || idx}`} message={m} />
                ))}

                {/* Active Multi-Agent Loading Indicator */}
                {loading && (
                  <div style={{
                    display: 'flex',
                    gap: '1rem',
                    padding: '1.25rem 1.5rem',
                    backgroundColor: 'var(--bg-surface)',
                    borderBottom: '1px solid var(--border-subtle)',
                    animation: 'fadeIn 0.2s ease-out'
                  }}>
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '10px',
                      backgroundColor: 'var(--accent-primary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#ffffff',
                      boxShadow: '0 2px 8px rgba(59, 130, 246, 0.35)'
                    }}>
                      <RefreshCw size={16} className="animate-spin" />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                          OmniDoc Multi-Agent Swarm Reasoning...
                        </span>
                      </div>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Query Planner → LanceDB Hybrid Retrieval → Kùzu Knowledge Graph → SymPy Math Engine → Groundedness Guard
                      </p>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Input Prompt Section with Voice and JIT Upload */}
          <div style={{
            padding: '0.85rem 1.5rem 1.15rem',
            backgroundColor: 'var(--bg-app)',
            borderTop: '1px solid var(--border-subtle)',
          }}>
            <div style={{ maxWidth: '860px', margin: '0 auto', width: '100%' }}>
              {/* JIT Upload Notification Pill */}
              {lastUploadedDoc && (
                <div style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  fontSize: '0.74rem',
                  backgroundColor: 'rgba(16, 185, 129, 0.1)',
                  color: 'var(--accent-emerald)',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.2rem 0.5rem',
                  marginBottom: '0.5rem'
                }}>
                  <CheckCircle2 size={12} />
                  <span>JIT Ingested: {lastUploadedDoc}</span>
                </div>
              )}

              <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleJitUpload}
                  accept=".pdf,.docx,.txt,.md"
                  style={{ display: 'none' }}
                />

                <textarea
                  ref={textareaRef}
                  value={inputQuery}
                  onChange={(e) => setInputQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`Ask a question or speak in ${language.toUpperCase()} (Voice STT/TTS ready)...`}
                  rows={2}
                  disabled={loading}
                  style={{
                    width: '100%',
                    padding: '0.85rem 6.5rem 0.85rem 2.85rem',
                    backgroundColor: 'var(--bg-surface)',
                    border: `1px solid ${isListening ? 'var(--accent-rose)' : 'var(--border-medium)'}`,
                    borderRadius: 'var(--radius-lg)',
                    fontSize: '0.92rem',
                    color: 'var(--text-primary)',
                    resize: 'none',
                    lineHeight: 1.5,
                  }}
                />

                {/* Left Attachment Icon for JIT File Upload */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadingJit}
                  title="Upload document for instant JIT parsing"
                  style={{
                    position: 'absolute',
                    left: '0.75rem',
                    bottom: '0.95rem',
                    color: uploadingJit ? 'var(--accent-primary)' : 'var(--text-dim)',
                    padding: '0.3rem',
                    borderRadius: 'var(--radius-sm)'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
                  onMouseLeave={(e) => e.currentTarget.style.color = uploadingJit ? 'var(--accent-primary)' : 'var(--text-dim)'}
                >
                  <Paperclip size={16} className={uploadingJit ? 'animate-spin' : ''} />
                </button>

                {/* Right Action Icons: Mic + Send */}
                <div style={{
                  position: 'absolute',
                  right: '0.75rem',
                  bottom: '0.85rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.45rem'
                }}>
                  {/* Speech Input Microphone Toggle */}
                  <button
                    type="button"
                    onClick={toggleVoiceInput}
                    title={isListening ? 'Stop recording voice' : 'Speak your query with microphone'}
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: 'var(--radius-md)',
                      backgroundColor: isListening ? 'rgba(239, 68, 68, 0.2)' : 'var(--bg-surface-elevated)',
                      color: isListening ? '#ef4444' : 'var(--text-muted)',
                      border: `1px solid ${isListening ? '#ef4444' : 'transparent'}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'var(--transition-fast)'
                    }}
                  >
                    {isListening ? <MicOff size={15} /> : <Mic size={15} />}
                  </button>

                  {/* Send Button */}
                  <button
                    type="submit"
                    disabled={!inputQuery.trim() || loading}
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: 'var(--radius-md)',
                      backgroundColor: inputQuery.trim() && !loading ? 'var(--accent-primary)' : 'var(--bg-surface-elevated)',
                      color: inputQuery.trim() && !loading ? '#ffffff' : 'var(--text-dim)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'var(--transition-fast)'
                    }}
                  >
                    <Send size={14} />
                  </button>
                </div>
              </form>

              {/* Status and Audio Wave Indicator */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginTop: '0.45rem',
                fontSize: '0.72rem',
                color: 'var(--text-dim)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                  <span>Press Enter to send</span>
                  {isListening && <AudioWaveVisualizer active={true} type="listening" />}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                  <ShieldCheck size={12} style={{ color: 'var(--accent-emerald)' }} />
                  <span>Web Speech & WeasyPrint Export Ready</span>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </main>
  );
};
