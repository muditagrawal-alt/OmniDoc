import { useMemo, useState } from 'react';
import { Calculator, Check, ChevronRight, Copy } from 'lucide-react';
import katex from 'katex';
import type { MathResult } from '../../api';
import { normalizeMath } from './normalize';
import styles from './MathBlock.module.css';

function renderTex(tex: string): string | null {
  if (!tex) return null;
  try {
    // KaTeX escapes its input and `trust` is off, so the HTML is safe to inject.
    return katex.renderToString(tex, { displayMode: true, throwOnError: true, strict: 'ignore', output: 'htmlAndMathml' });
  } catch {
    return null;
  }
}

/** A verified calculation: what was computed, the formula, the result and its inputs. */
export function MathBlock({ result }: { result: MathResult }) {
  const m = useMemo(() => normalizeMath(result), [result]);
  const html = useMemo(() => renderTex(m.formula), [m.formula]);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  const computation = m.code || m.steps.join('\n');

  return (
    <section className={styles.block} aria-label={`Calculation: ${m.task}`}>
      <header className={styles.head}>
        <span className={styles.kind}>
          <Calculator size={14} strokeWidth={1.75} aria-hidden="true" /> Calculation
        </span>
        {m.result && (
          <button
            type="button"
            className="icon-btn icon-btn-sm"
            aria-label={copied ? 'Copied' : 'Copy result'}
            title="Copy result"
            onClick={() =>
              navigator.clipboard?.writeText(`${m.result}${m.units ? ` ${m.units}` : ''}`).then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1400);
              })
            }
          >
            {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.75} />}
          </button>
        )}
      </header>

      <p className={styles.task}>{m.task}</p>

      {m.formula &&
        (html ? (
          <div className={styles.formula} dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code className={styles.formulaText}>{m.formula}</code>
        ))}

      {m.result && (
        <p className={styles.result}>
          <span className={styles.equals} aria-hidden="true">=</span>
          <span className={styles.value}>{m.result}</span>
          {m.units && <span className={styles.units}>{m.units}</span>}
        </p>
      )}

      {m.inputs.length > 0 && (
        <dl className={styles.inputs}>
          {m.inputs.map(([k, v]) => (
            <div key={k} className={styles.inputRow}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}

      {m.assumptions.length > 0 && (
        <ul className={styles.assumptions} aria-label="Assumptions">
          {m.assumptions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      )}

      {computation && (
        <div className={styles.computation}>
          <button type="button" className={styles.disclosure} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <ChevronRight size={14} strokeWidth={2} className={styles.chevron} data-open={open} />
            {open ? 'Hide computation' : 'Show computation'}
          </button>
          {open && <pre className={styles.code}>{computation}</pre>}
        </div>
      )}
    </section>
  );
}
