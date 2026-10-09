import { useState } from 'react';
import { AlertTriangle, ArrowRightLeft, Check, ChevronRight, CircleDashed, MinusCircle, ScanSearch, Table2 } from 'lucide-react';
import type { SentenceCheck, SentenceVerdict, TableResult, Verification } from '../../api';
import { pluralize } from '../../lib/format';
import styles from './Evidence.module.css';

const ICON = { size: 14, strokeWidth: 1.9 } as const;
const PREVIEW_ROWS = 8;

function formatCell(v: string | number | null): string {
  if (v == null) return '';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return v;
}

/** The result of a SQL query the table agent ran, with the query and a link to the table. */
export function TableResults({ tables, onOpen }: { tables: TableResult[]; onOpen: (t: TableResult) => void }) {
  // A small table is also given to the writer whole; "Show table" already opens it.
  const shown = tables.filter((t) => t.purpose !== 'all rows' || !tables.some((o) => o !== t && o.table === t.table && o.purpose !== 'all rows'));
  if (!shown.length) return null;
  return (
    <div className={styles.tables}>
      {shown.map((t, i) => (
        <TableResultBlock key={`${t.table}-${i}`} result={t} onOpen={() => onOpen(t)} />
      ))}
    </div>
  );
}

function TableResultBlock({ result, onOpen }: { result: TableResult; onOpen: () => void }) {
  const [showSql, setShowSql] = useState(false);
  const rows = result.rows.slice(0, PREVIEW_ROWS);
  return (
    <figure className={styles.tableResult}>
      <figcaption className={styles.tableHead}>
        <Table2 size={15} strokeWidth={1.75} aria-hidden="true" />
        <span className={styles.tableTitle}>{result.title || result.table}</span>
        {result.page != null && <span className={styles.tableMeta}>p. {result.page}</span>}
        <span className={styles.tableMeta}>{result.purpose === 'all rows' ? 'all rows' : pluralize(result.row_count, 'row')}</span>
        <span className={styles.spacer} />
        <button type="button" className="btn btn-ghost btn-sm" aria-expanded={showSql} onClick={() => setShowSql((s) => !s)}>
          SQL
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onOpen}>
          <ScanSearch size={14} strokeWidth={1.75} /> Show table
        </button>
      </figcaption>
      {result.purpose && result.purpose !== 'all rows' && result.purpose !== result.question && (
        <p className={styles.purpose}>{result.purpose}</p>
      )}
      {showSql && <pre className={styles.sql}>{result.sql}</pre>}
      {rows.length > 0 && result.columns.length > 0 ? (
        <div className={styles.gridWrap}>
          <table className={styles.grid}>
            <thead>
              <tr>
                {result.columns.map((c, i) => (
                  <th key={i}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((v, ci) => (
                    <td key={ci} data-num={typeof v === 'number' || undefined}>
                      {formatCell(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className={styles.empty}>The query returned no rows.</p>
      )}
      {(result.row_count > rows.length || result.truncated) && (
        <p className={styles.more}>
          Showing {rows.length} of {result.truncated ? 'more than ' : ''}
          {result.row_count.toLocaleString()} rows
        </p>
      )}
    </figure>
  );
}

const VERDICT: Record<SentenceVerdict, { label: string; tone: 'good' | 'warn' | 'bad' | 'muted' }> = {
  supported: { label: 'Supported', tone: 'good' },
  partial: { label: 'Partly supported', tone: 'warn' },
  unsupported: { label: 'Not in the sources', tone: 'bad' },
  contradicted: { label: 'Contradicted', tone: 'bad' },
  no_claim: { label: 'No claim', tone: 'muted' },
  unchecked: { label: 'Not checked', tone: 'muted' },
};

function VerdictIcon({ verdict }: { verdict: SentenceVerdict }) {
  if (verdict === 'supported') return <Check {...ICON} />;
  if (verdict === 'partial') return <MinusCircle {...ICON} />;
  if (verdict === 'unsupported' || verdict === 'contradicted') return <AlertTriangle {...ICON} />;
  return <CircleDashed {...ICON} />;
}

/**
 * Sentence-by-sentence result of the citation check: which sentences the cited passages
 * support, which they do not, and which citations were corrected.
 */
export function SentenceChecks({
  verification,
  onOpen,
}: {
  verification: Verification;
  onOpen: (sentence: SentenceCheck, n: number) => void;
}) {
  const sentences = (verification.sentences ?? []).filter((s) => s.verdict !== 'no_claim');
  if (!sentences.length) {
    return <p className={styles.checkNote}>{verification.feedback || 'There were no factual sentences to check.'}</p>;
  }
  const counts = {
    supported: sentences.filter((s) => s.verdict === 'supported').length,
    partial: sentences.filter((s) => s.verdict === 'partial').length,
    bad: sentences.filter((s) => s.verdict === 'unsupported' || s.verdict === 'contradicted').length,
    corrected: sentences.filter((s) => s.corrected_to?.length).length,
  };
  return (
    <div className={styles.checks}>
      <p className={styles.checkSummary}>
        {pluralize(sentences.length, 'sentence')} checked against the passages they cite: {counts.supported} supported
        {counts.partial ? `, ${counts.partial} partly` : ''}
        {counts.bad ? `, ${counts.bad} not found in the sources` : ''}
        {counts.corrected ? `. ${pluralize(counts.corrected, 'citation')} corrected` : ''}.
      </p>
      <ol className={styles.checkList}>
        {sentences.map((s) => {
          const v = VERDICT[s.verdict] ?? VERDICT.unchecked;
          const target = s.citations[0] ?? s.supported_by[0];
          const text = s.text.replace(/\s*\[\d{1,3}\]/g, '').trim();
          return (
            <li key={s.id} className={styles.check} data-tone={v.tone}>
              <span className={styles.checkIcon} aria-hidden="true">
                <VerdictIcon verdict={s.verdict} />
              </span>
              <div className={styles.checkBody}>
                <span className={styles.checkVerdict}>{v.label}</span>
                {target != null ? (
                  <button type="button" className={styles.checkText} onClick={() => onOpen(s, target)} title="Show the cited passage">
                    {text}
                  </button>
                ) : (
                  <span className={styles.checkText}>{text}</span>
                )}
                {s.reason && s.verdict !== 'supported' && <span className={styles.checkReason}>{s.reason}</span>}
                {s.corrected_to && s.corrected_to.length > 0 && (
                  <span className={styles.checkFix}>
                    <ArrowRightLeft size={12} strokeWidth={2} aria-hidden="true" /> Citation corrected to{' '}
                    {s.corrected_to.map((n) => `[${n}]`).join('')}
                  </span>
                )}
              </div>
              <span className={styles.checkCites}>
                {s.citations.map((n) => (
                  <button key={n} type="button" onClick={() => onOpen(s, n)} aria-label={`Show source ${n}`}>
                    {n}
                  </button>
                ))}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ChecksToggle({ open, onToggle, count }: { open: boolean; onToggle: () => void; count: number }) {
  if (!count) return null;
  return (
    <button type="button" className={styles.checksToggle} aria-expanded={open} onClick={onToggle}>
      Sentence check
      <ChevronRight size={13} strokeWidth={2} className={styles.chevron} data-open={open} />
    </button>
  );
}
