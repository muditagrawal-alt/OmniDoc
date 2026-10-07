import React, { useState } from 'react';
import {
  Copy,
  Check,
  FileDown,
  Sparkles,
  User,
  ShieldCheck,
  FileText,
  Volume2,
  VolumeX
} from 'lucide-react';
import { api } from '../api';
import type { ChatMessage } from '../api';
import { voiceController } from '../utils/voice';
import { AudioWaveVisualizer } from './AudioWaveVisualizer';
import { MathCard } from './MathCard';
import { EvidenceCard } from './EvidenceCard';
import { ConflictBanner } from './ConflictBanner';
import { AgentTraceViewer } from './AgentTraceViewer';
import { MarkdownRenderer } from './MarkdownRenderer';
import { InteractiveChartViewer } from './InteractiveChartViewer';
import { InteractiveMapViewer } from './InteractiveMapViewer';

interface ChatMessageItemProps {
  message: ChatMessage;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null);
  const [speaking, setSpeaking] = useState(false);

  const isAssistant = message.role === 'assistant';
  const meta = message.metadata || {};

  const toggleSpeak = () => {
    if (speaking) {
      voiceController.stopSpeaking();
      setSpeaking(false);
    } else {
      voiceController.speak(message.content, () => setSpeaking(false));
      setSpeaking(true);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = async (type: 'pdf' | 'docx') => {
    setExporting(type);
    try {
      const singleTurnMessage = [
        {
          role: 'assistant',
          content: message.content,
          sources: meta.sources || [],
          conflicts: meta.conflicts || [],
          math_result: meta.math_results?.[0],
          math_results: meta.math_results || [],
          visual_artifacts: meta.visual_artifacts || [],
          geo_locations: meta.geo_locations || [],
          graph_entities: meta.graph_entities || []
        }
      ];
      const blob = type === 'pdf'
        ? await api.exportPdf(undefined, singleTurnMessage, 'OmniDoc Analysis Excerpt')
        : await api.exportDocx(undefined, singleTurnMessage, 'OmniDoc Analysis Excerpt');

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `OmniDoc_Analysis.${type}`;
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

  return (
    <div style={{
      display: 'flex',
      gap: '1rem',
      padding: '1.25rem 1.5rem',
      backgroundColor: isAssistant ? 'var(--bg-surface)' : 'transparent',
      borderBottom: '1px solid var(--border-subtle)',
      animation: 'fadeIn 0.2s ease-out'
    }}>
      {/* Avatar */}
      <div style={{
        width: '32px',
        height: '32px',
        borderRadius: isAssistant ? '10px' : 'var(--radius-full)',
        backgroundColor: isAssistant ? 'var(--accent-primary)' : 'var(--bg-surface-elevated)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#ffffff',
        flexShrink: 0,
        boxShadow: isAssistant ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none',
      }}>
        {isAssistant ? <Sparkles size={16} /> : <User size={16} style={{ color: 'var(--text-muted)' }} />}
      </div>

      {/* Message Content Body */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name & Role Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.4rem' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {isAssistant ? 'OmniDoc Neural Agent' : 'You'}
          </span>
          {isAssistant && meta.groundedness_score && (
            <span style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
              fontSize: '0.72rem',
              color: 'var(--accent-emerald)',
              fontWeight: 500,
            }}>
              <ShieldCheck size={12} />
              {Math.round(meta.groundedness_score * 100)}% Grounded
            </span>
          )}
        </div>

        {/* Multi-Agent Reasoning Traces (if assistant) */}
        {isAssistant && meta.thought_process && meta.thought_process.length > 0 && (
          <AgentTraceViewer
            traces={meta.thought_process}
            groundednessScore={meta.groundedness_score}
          />
        )}

        {/* Text Body - Clean Editorial Markdown for Assistant, Direct text for User */}
        <div style={{
          color: 'var(--text-primary)',
          fontSize: '0.94rem',
          lineHeight: 1.65,
          wordBreak: 'break-word',
          marginBottom: '0.5rem'
        }}>
          {isAssistant ? (
            <MarkdownRenderer content={message.content} />
          ) : (
            <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-primary)' }}>
              {message.content}
            </div>
          )}
        </div>

        {/* Interactive Geographical Intelligence Maps */}
        {meta.geo_locations && meta.geo_locations.length > 0 && (
          <InteractiveMapViewer locations={meta.geo_locations} />
        )}

        {/* Mathematical Execution Cards */}
        {meta.math_results && meta.math_results.map((m, idx) => (
          <MathCard key={idx} math={m} />
        ))}

        {/* Interactive Visual Charts & Trend Artifacts */}
        {meta.visual_artifacts && meta.visual_artifacts.map((v, idx) => (
          <InteractiveChartViewer key={idx} artifact={v} />
        ))}

        {/* Detected Discrepancies & Conflicts */}
        {meta.conflicts && meta.conflicts.length > 0 && (
          <ConflictBanner conflicts={meta.conflicts} />
        )}

        {/* Grounded Evidence Citations */}
        {meta.sources && meta.sources.length > 0 && (
          <EvidenceCard sources={meta.sources} />
        )}

        {/* Action Toolbar */}
        {isAssistant && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.65rem',
            marginTop: '0.75rem',
            paddingTop: '0.5rem',
            borderTop: '1px solid rgba(255, 255, 255, 0.04)'
          }}>
            <button
              onClick={toggleSpeak}
              title={speaking ? 'Stop speech' : 'Read aloud with voice'}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                fontSize: '0.75rem',
                color: speaking ? 'var(--accent-primary)' : 'var(--text-dim)',
                padding: '0.25rem 0.5rem',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: speaking ? 'rgba(59, 130, 246, 0.12)' : 'transparent',
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
              onMouseLeave={(e) => e.currentTarget.style.color = speaking ? 'var(--accent-primary)' : 'var(--text-dim)'}
            >
              {speaking ? <VolumeX size={13} style={{ color: 'var(--accent-rose)' }} /> : <Volume2 size={13} />}
              <span>{speaking ? 'Stop Voice' : 'Read Aloud'}</span>
            </button>

            {speaking && <AudioWaveVisualizer active={true} type="speaking" />}

            <button
              onClick={handleCopy}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                fontSize: '0.75rem',
                color: 'var(--text-dim)',
                padding: '0.25rem 0.5rem',
                borderRadius: 'var(--radius-sm)'
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
            >
              {copied ? <Check size={12} style={{ color: 'var(--accent-emerald)' }} /> : <Copy size={12} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>

            <button
              onClick={() => handleExport('pdf')}
              disabled={exporting !== null}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                fontSize: '0.75rem',
                color: 'var(--text-dim)',
                padding: '0.25rem 0.5rem',
                borderRadius: 'var(--radius-sm)'
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = '#93c5fd'}
              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
            >
              <FileDown size={12} />
              <span>{exporting === 'pdf' ? 'Generating PDF...' : 'Export WeasyPrint PDF'}</span>
            </button>

            <button
              onClick={() => handleExport('docx')}
              disabled={exporting !== null}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                fontSize: '0.75rem',
                color: 'var(--text-dim)',
                padding: '0.25rem 0.5rem',
                borderRadius: 'var(--radius-sm)'
              }}
              onMouseEnter={(e) => e.currentTarget.style.color = '#93c5fd'}
              onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
            >
              <FileText size={12} />
              <span>{exporting === 'docx' ? 'Generating DOCX...' : 'Export Word (.docx)'}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
