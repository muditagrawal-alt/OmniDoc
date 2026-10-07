import { memo, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Copy,
  FileText,
  Globe2,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Volume2,
  VolumeX,
} from 'lucide-react';
import type { AgentStep, ChatMessage, Source, Verification } from '../../api';
import { normalizeAnswer } from '../../lib/normalize';
import type { NormalizedAnswer } from '../../lib/normalize';
import { formatDuration, pluralize } from '../../lib/format';
import { voiceController } from '../../utils/voice';
import { ChartFigure, MathBlock } from '../artifacts';
import type { Artifact } from '../artifacts';
import { Markdown } from './Markdown';
import { sourceLabel } from './Citation';
import styles from './chat.module.css';

const ICON = { size: 15, strokeWidth: 1.75 } as const;

export function UserMessage({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={styles.userRow}>
      <div className={styles.userBubble}>{message.content}</div>
      <div className={styles.userActions}>
        <button
          type="button"
          className="icon-btn icon-btn-sm"
          aria-label={copied ? 'Copied' : 'Copy message'}
          onClick={() =>
            navigator.clipboard?.writeText(message.content).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1400);
            })
          }
        >
          {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.75} />}
        </button>
      </div>
    </div>
  );
}

interface AssistantMessageProps {
  message: ChatMessage;
  liveSteps?: AgentStep[];
  onRetry?: () => void;
  onOpenArtifact: (a: Artifact) => void;
  onViewOnGlobe: (entityNames: string[]) => void;
  language: string;
}

function VerificationBadge({ v }: { v: Verification | null }) {
  if (!v) return null;
  if (v.status === 'unverified' || v.score == null) {
    return (
      <span className={styles.badge} data-tone="muted" title={v.feedback || 'The answer could not be checked against its sources.'}>
        <CircleDashed {...ICON} /> Not verified
      </span>
    );
  }
  const verified = v.status === 'verified';
  return (
    <span
      className={styles.badge}
      data-tone={verified ? 'good' : 'warn'}
      title={
        verified
          ? 'Every checked claim is supported by the cited sources.'
          : `${v.unsupported} claim${v.unsupported === 1 ? '' : 's'} could not be matched to a source.`
      }
    >
      {verified ? <ShieldCheck {...ICON} /> : <ShieldAlert {...ICON} />}
      {verified ? 'Supported by sources' : 'Partly supported'}
      <span className={styles.badgeScore}>{v.score.toFixed(2)}</span>
    </span>
  );
}

function StepTrace({ steps, live, elapsedMs }: { steps: AgentStep[]; live: boolean; elapsedMs?: number }) {
  const [open, setOpen] = useState(false);
  const total = elapsedMs ?? steps.reduce((acc, s) => acc + (s.duration_ms || 0), 0);
  if (!steps.length && !live) return null;
  const current = steps[steps.length - 1];

  return (
    <div className={styles.trace}>
      <button type="button" className={styles.traceToggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronRight size={14} strokeWidth={2} className={styles.traceChevron} data-open={open} />
        {live ? (
          <span className="shimmer-text">{current ? `${current.label}…` : 'Starting…'}</span>
        ) : (
          <span>
            Worked for {formatDuration(total) || 'a moment'}
            <span className={styles.traceCount}> · {pluralize(steps.length, 'step')}</span>
          </span>
        )}
      </button>
      {open && (
        <ol className={styles.traceList}>
          {steps.map((s, i) => (
            <li key={`${s.node}-${i}`} className={styles.traceItem} data-live={live && i === steps.length - 1}>
              <span className={styles.traceDot} aria-hidden="true" />
              <span className={styles.traceLabel}>{s.label}</span>
              {s.detail && <span className={styles.traceDetail}>{s.detail}</span>}
              {s.duration_ms != null && s.duration_ms > 0 && (
                <span className={styles.traceTime}>{formatDuration(s.duration_ms)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function SourceList({ sources, highlight, listRef }: { sources: Source[]; highlight: number | null; listRef: React.RefObject<HTMLDivElement | null> }) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (highlight != null) setExpanded(true);
  }, [highlight]);
  if (!sources.length) return null;
  // The summary names documents; graph relations and calculations are listed in the grid.
  const docs = [...new Set(sources.map((s) => (s.doc_title || s.doc_id || '').replace(/\.(pdf|docx|txt|md)$/i, '')).filter(Boolean))];

  return (
    <div className={styles.sources} ref={listRef}>
      <button type="button" className={styles.sourcesToggle} aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
        <FileText {...ICON} />
        <span className={styles.sourcesCount}>{pluralize(sources.length, 'source')}</span>
        {docs.length > 0 && (
          <span className={styles.sourcesDocs}>{docs.slice(0, 3).join(' · ')}{docs.length > 3 ? ` +${docs.length - 3}` : ''}</span>
        )}
        <ChevronRight size={14} strokeWidth={2} className={styles.traceChevron} data-open={expanded} />
      </button>
      {expanded && (
        <ol className={styles.sourceGrid}>
          {sources.map((s) => (
            <li key={s.n} id={`src-${s.n}`} className={styles.sourceCard} data-highlight={highlight === s.n}>
              <div className={styles.sourceHead}>
                <span className={styles.sourceNum}>{s.n}</span>
                <span className={styles.sourceTitle}>{sourceLabel(s)}</span>
                {s.page != null && <span className={styles.sourceMeta}>p. {s.page}</span>}
              </div>
              {s.section && <div className={styles.sourceSection}>{s.section}</div>}
              <p className={styles.sourceSnippet}>{s.snippet}</p>
              {typeof s.score === 'number' && (
                <div className={styles.sourceScore} title="Relevance score from the retriever / reranker">
                  relevance <span className="num">{s.score.toFixed(2)}</span>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ConflictNotes({ answer }: { answer: NormalizedAnswer }) {
  if (!answer.conflicts.length) return null;
  return (
    <div className={styles.conflicts} role="note">
      <div className={styles.conflictsHead}>
        <AlertTriangle {...ICON} /> Sources disagree
      </div>
      <ul>
        {answer.conflicts.map((c, i) => (
          <li key={i}>
            <span className={styles.conflictClaim}>{c.conflicting_claim}</span>
            {c.rationale && <span className={styles.conflictWhy}>{c.rationale}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssistantMessageInner({ message, liveSteps, onRetry, onOpenArtifact, onViewOnGlobe, language }: AssistantMessageProps) {
  const answer = useMemo(() => normalizeAnswer(message.metadata), [message.metadata]);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const sourcesRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => voiceController.stopSpeaking(), []);

  const live = !!message.pending;
  const steps = live ? liveSteps ?? [] : answer.steps;

  const onCite = (n: number) => {
    setHighlight(n);
    window.setTimeout(() => {
      document.getElementById(`src-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 30);
  };

  const artifacts: Artifact[] = useMemo(
    () => answer.charts.map((chart, i) => ({ kind: 'chart' as const, id: `${message.id}-chart-${i}`, title: chart.title || 'Chart', chart })),
    [answer, message.id],
  );

  if (message.error) {
    return (
      <div className={styles.assistant}>
        <div className={styles.errorBox} role="alert">
          <AlertTriangle {...ICON} />
          <span>{message.error}</span>
          {onRetry && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
              <RotateCcw size={14} strokeWidth={1.75} /> Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  const entityNames = answer.graph.nodes.map((n) => n.name).filter(Boolean);

  return (
    <article className={styles.assistant} aria-busy={live}>
      <StepTrace steps={steps} live={live} elapsedMs={live ? undefined : answer.elapsedMs} />

      {live ? (
        <div className={styles.skeleton} aria-hidden="true">
          <span style={{ width: '92%' }} />
          <span style={{ width: '78%' }} />
          <span style={{ width: '85%' }} />
        </div>
      ) : (
        <>
          <Markdown text={message.content} sources={answer.sources} onCite={onCite} />

          {answer.math.length > 0 && (
            <div className={styles.artifactStack}>
              {answer.math.map((m, i) => (
                <MathBlock key={i} result={m} />
              ))}
            </div>
          )}

          {answer.charts.length > 0 && (
            <div className={styles.artifactStack}>
              {answer.charts.map((chart, i) => (
                <ChartFigure key={i} chart={chart} variant="inline" onCite={onCite} onExpand={() => onOpenArtifact(artifacts[i])} />
              ))}
            </div>
          )}

          <ConflictNotes answer={answer} />

          <div className={styles.answerFooter}>
            <div className={styles.actions}>
              <button
                type="button"
                className="icon-btn icon-btn-sm"
                aria-label={copied ? 'Copied' : 'Copy answer'}
                title="Copy"
                onClick={() =>
                  navigator.clipboard?.writeText(message.content).then(() => {
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1400);
                  })
                }
              >
                {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.75} />}
              </button>
              {voiceController.isSpeechSupported() && (
                <button
                  type="button"
                  className="icon-btn icon-btn-sm"
                  aria-pressed={speaking}
                  aria-label={speaking ? 'Stop reading aloud' : 'Read aloud'}
                  title={speaking ? 'Stop' : 'Read aloud'}
                  onClick={() => {
                    if (speaking) {
                      voiceController.stopSpeaking();
                      setSpeaking(false);
                    } else {
                      voiceController.setLanguage(language);
                      voiceController.speak(message.content, () => setSpeaking(false));
                      setSpeaking(true);
                    }
                  }}
                >
                  {speaking ? <VolumeX size={14} strokeWidth={1.75} /> : <Volume2 size={14} strokeWidth={1.75} />}
                </button>
              )}
              {entityNames.length > 0 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => onViewOnGlobe(entityNames)}>
                  <Globe2 size={14} strokeWidth={1.75} /> View {pluralize(entityNames.length, 'entity', 'entities')} on globe
                </button>
              )}
            </div>
            <VerificationBadge v={answer.verification} />
          </div>

          <SourceList sources={answer.sources} highlight={highlight} listRef={sourcesRef} />
        </>
      )}
    </article>
  );
}

export const AssistantMessage = memo(AssistantMessageInner);
