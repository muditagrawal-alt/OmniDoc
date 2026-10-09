import { memo, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Copy,
  ExternalLink,
  FileText,
  Globe2,
  RotateCcw,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  Volume2,
  VolumeX,
} from 'lucide-react';
import type { AgentStep, ChatMessage, SentenceCheck, Source, TableResult, Usage, Verification } from '../../api';
import { normalizeAnswer } from '../../lib/normalize';
import type { NormalizedAnswer } from '../../lib/normalize';
import { formatDuration, pluralize } from '../../lib/format';
import { voiceController } from '../../utils/voice';
import { ChartFigure, MathBlock } from '../artifacts';
import type { Artifact } from '../artifacts';
import type { ViewerTarget } from '../viewer/SourceViewer';
import { Markdown } from './Markdown';
import type { SentenceFlag } from './Markdown';
import { sourceLabel } from './Citation';
import { ChecksToggle, SentenceChecks, TableResults } from './Evidence';
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
  /** Opens the cited passage in its document, highlighting the sentence that supports `claim` */
  onOpenSource: (target: ViewerTarget) => void;
  onViewOnGlobe: (entityNames: string[]) => void;
  language: string;
}

/** Sources that live in a document the viewer can open. */
function openableInDocument(s: Source): boolean {
  if (s.kind === 'web') return !!s.url;
  return !!s.doc_id && s.doc_id !== '_library' && !['math', 'conflict'].includes(s.kind);
}

function usageLabel(usage?: Usage): string {
  if (!usage || usage.calls == null) return '';
  const models = Object.keys(usage.models ?? {}).map((m) => m.split(':').slice(-1)[0].split('/').slice(-1)[0]);
  return `${pluralize(usage.calls, 'model call')}${models.length ? ` · ${[...new Set(models)].join(', ')}` : ''}`;
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
          ? 'Every checked sentence is supported by the passages it cites.'
          : `${v.unsupported} sentence${v.unsupported === 1 ? '' : 's'} could not be matched to the cited passages.`
      }
    >
      {verified ? <ShieldCheck {...ICON} /> : <ShieldAlert {...ICON} />}
      {verified ? 'Supported by sources' : 'Partly supported'}
      <span className={styles.badgeScore}>{v.score.toFixed(2)}</span>
    </span>
  );
}

function StepTrace({ steps, live, elapsedMs, usage }: { steps: AgentStep[]; live: boolean; elapsedMs?: number; usage?: Usage }) {
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
            <span className={styles.traceCount}>
              {' '}
              · {pluralize(steps.length, 'step')}
              {usageLabel(usage) ? ` · ${usageLabel(usage)}` : ''}
            </span>
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

interface SourceListProps {
  sources: Source[];
  highlight: number | null;
  listRef: React.RefObject<HTMLDivElement | null>;
  idPrefix: string;
  onOpen: (s: Source) => void;
}

function SourceList({ sources, highlight, listRef, idPrefix, onOpen }: SourceListProps) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (highlight != null) setExpanded(true);
  }, [highlight]);
  if (!sources.length) return null;
  // The summary names documents; graph relations and calculations are listed in the grid.
  const docs = [...new Set(sources.map((s) => (s.doc_title || s.doc_id || '').replace(/\.[a-z0-9]{2,5}$/i, '')).filter(Boolean))];

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
            <li key={s.n} id={`${idPrefix}-${s.n}`} className={styles.sourceCard} data-highlight={highlight === s.n}>
              <div className={styles.sourceHead}>
                <span className={styles.sourceNum}>{s.n}</span>
                <span className={styles.sourceTitle}>{sourceLabel(s)}</span>
                {s.page != null && <span className={styles.sourceMeta}>p. {s.page}</span>}
                {openableInDocument(s) && (
                  <button
                    type="button"
                    className={`icon-btn icon-btn-sm ${styles.sourceOpen}`}
                    aria-label={s.kind === 'web' ? `Read source ${s.n} here` : `Show source ${s.n} in the document`}
                    title={s.kind === 'web' ? 'Read the page here' : 'Show in the document'}
                    onClick={() => onOpen(s)}
                  >
                    <ScanSearch size={14} strokeWidth={1.75} />
                  </button>
                )}
                {s.kind === 'web' && s.url && (
                  <a className={`icon-btn icon-btn-sm ${styles.sourceOpen}`} href={s.url} target="_blank" rel="noreferrer noopener" aria-label={`Open source ${s.n} on its site`} title={s.url}>
                    <ExternalLink size={14} strokeWidth={1.75} />
                  </a>
                )}
              </div>
              {s.kind === 'web' && s.site && (
                <div className={styles.sourceSection}>
                  <Globe2 size={11} strokeWidth={2} /> {s.site}
                  {s.published ? ` · ${s.published.slice(0, 10)}` : ''}
                </div>
              )}
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

function AssistantMessageInner({ message, liveSteps, onRetry, onOpenArtifact, onOpenSource, onViewOnGlobe, language }: AssistantMessageProps) {
  const answer = useMemo(() => normalizeAnswer(message.metadata), [message.metadata]);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [checksOpen, setChecksOpen] = useState(false);
  const sourcesRef = useRef<HTMLDivElement>(null);
  const idPrefix = `src-${message.id ?? 'live'}`;

  useEffect(() => () => voiceController.stopSpeaking(), []);

  const live = !!message.pending;
  const steps = live ? liveSteps ?? [] : answer.steps;

  const flags: SentenceFlag[] = useMemo(
    () =>
      (answer.verification?.sentences ?? [])
        .filter((c) => c.verdict === 'unsupported' || c.verdict === 'contradicted' || c.verdict === 'partial')
        .map((c) => ({ text: c.text, verdict: c.verdict, reason: c.reason })),
    [answer.verification],
  );
  const checked = (answer.verification?.sentences ?? []).filter((c) => c.verdict !== 'no_claim').length;

  const openSource = (s: Source, claim?: string) => {
    if (s.kind === 'web' && s.url) {
      onOpenSource({ key: `${message.id ?? 'live'}-${s.n}-${Date.now()}`, docId: '', url: s.url, docTitle: s.title,
                     claim, passage: s.snippet, label: `Source ${s.n} · ${s.site || 'web'}` });
      return;
    }
    const table = s.kind === 'table' ? answer.tables.find((t) => t.table === s.table) : undefined;
    onOpenSource({
      key: `${message.id ?? 'live'}-${s.n}-${Date.now()}`,
      docId: s.doc_id,
      docTitle: s.doc_title,
      page: s.page,
      chunkId: s.chunk_id,
      claim,
      passage: s.snippet,
      table: s.kind === 'table' ? s.table : undefined,
      sql: table?.sql,
      label: `Source ${s.n}`,
    });
  };

  /** A citation opens its passage in the document (and marks the source card). */
  const onCite = (n: number, claim?: string) => {
    setHighlight(n);
    const source = answer.sources.find((s) => s.n === n);
    if (source && openableInDocument(source)) {
      openSource(source, claim);
      return;
    }
    window.setTimeout(() => {
      document.getElementById(`${idPrefix}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 30);
  };

  const openTable = (t: TableResult) =>
    onOpenSource({
      key: `${message.id ?? 'live'}-${t.table}-${Date.now()}`,
      docId: t.doc_id,
      page: t.page,
      table: t.table,
      sql: t.sql,
      label: 'Table',
    });

  const openCheck = (c: SentenceCheck, n: number) => onCite(n, c.text.replace(/\s*\[\d{1,3}\]/g, '').trim());

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
      <StepTrace steps={steps} live={live} elapsedMs={live ? undefined : answer.elapsedMs} usage={answer.usage} />

      {live && message.content ? (
        <div className={styles.streaming} aria-live="off">
          <Markdown text={message.content} sources={answer.sources} onCite={onCite} />
        </div>
      ) : live ? (
        <div className={styles.skeleton} aria-hidden="true">
          <span style={{ width: '92%' }} />
          <span style={{ width: '78%' }} />
          <span style={{ width: '85%' }} />
        </div>
      ) : (
        <>
          <Markdown text={message.content} sources={answer.sources} onCite={onCite} flags={flags} />

          <TableResults tables={answer.tables} onOpen={openTable} />

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
            <div className={styles.verify}>
              <ChecksToggle open={checksOpen} onToggle={() => setChecksOpen((o) => !o)} count={checked} />
              <VerificationBadge v={answer.verification} />
            </div>
          </div>

          {checksOpen && answer.verification && <SentenceChecks verification={answer.verification} onOpen={openCheck} />}

          <SourceList sources={answer.sources} highlight={highlight} listRef={sourcesRef} idPrefix={idPrefix} onOpen={(s) => openSource(s)} />
        </>
      )}
    </article>
  );
}

export const AssistantMessage = memo(AssistantMessageInner);
