import { Fragment, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import katex from 'katex';
import { Check, Copy } from 'lucide-react';
import type { Source } from '../../api';
import { Citation } from './Citation';
import styles from './Markdown.module.css';

interface MarkdownProps {
  text: string;
  sources?: Source[];
  onCite?: (n: number) => void;
}

type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; start: number; items: ListItem[] }
  | { kind: 'code'; lang: string; code: string }
  | { kind: 'math'; tex: string }
  | { kind: 'quote'; text: string }
  | { kind: 'table'; header: string[]; align: Array<'left' | 'right' | 'center'>; rows: string[][] }
  | { kind: 'rule' };

interface ListItem {
  text: string;
  children: Block[];
}

const LIST_RE = /^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$/;
const TABLE_SEP_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

/** Line-oriented markdown parser covering what the synthesis agent emits. */
function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;

  const parseList = (baseIndent: number): { block: Block; next: number } => {
    const first = LIST_RE.exec(lines[i])!;
    const ordered = /\d/.test(first[2]);
    const items: ListItem[] = [];
    while (i < lines.length) {
      const m = LIST_RE.exec(lines[i]);
      if (!m) {
        // Continuation line of the previous item
        if (lines[i].trim() && items.length && /^\s{2,}/.test(lines[i]) && !LIST_RE.test(lines[i])) {
          items[items.length - 1].text += ' ' + lines[i].trim();
          i++;
          continue;
        }
        break;
      }
      const indent = m[1].replace(/\t/g, '  ').length;
      if (indent < baseIndent) break;
      if (indent > baseIndent && items.length) {
        const nested = parseList(indent);
        items[items.length - 1].children.push(nested.block);
        continue;
      }
      if (/\d/.test(m[2]) !== ordered && items.length) break;
      items.push({ text: m[3], children: [] });
      i++;
    }
    return { block: { kind: 'list', ordered, start: ordered ? parseInt(first[2], 10) || 1 : 1, items }, next: i };
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    const fence = /^(```|~~~)\s*([\w+-]*)/.exec(trimmed);
    if (fence) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i++]);
      i++;
      blocks.push({ kind: 'code', lang: fence[2] || '', code: code.join('\n') });
      continue;
    }

    if (trimmed.startsWith('$$')) {
      let tex = trimmed.slice(2);
      if (tex.endsWith('$$') && tex.length >= 2) {
        tex = tex.slice(0, -2);
        i++;
      } else {
        const parts = [tex];
        i++;
        while (i < lines.length && !lines[i].includes('$$')) parts.push(lines[i++]);
        if (i < lines.length) parts.push(lines[i++].split('$$')[0]);
        tex = parts.join('\n');
      }
      blocks.push({ kind: 'math', tex: tex.trim() });
      continue;
    }
    if (trimmed.startsWith('\\[')) {
      const parts = [trimmed.slice(2)];
      i++;
      while (i < lines.length && !parts[parts.length - 1].includes('\\]')) parts.push(lines[i++]);
      blocks.push({ kind: 'math', tex: parts.join('\n').replace(/\\\]\s*$/, '').trim() });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*?)\s*#*$/.exec(trimmed);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] });
      i++;
      continue;
    }

    if (/^([-*_])(\s*\1){2,}$/.test(trimmed)) {
      blocks.push({ kind: 'rule' });
      i++;
      continue;
    }

    if (trimmed.includes('|') && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])) {
      const header = splitRow(trimmed);
      const align = splitRow(lines[i + 1]).map((c) =>
        c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : 'left',
      ) as Array<'left' | 'right' | 'center'>;
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
      blocks.push({ kind: 'table', header, align, rows });
      continue;
    }

    if (LIST_RE.test(line)) {
      const indent = LIST_RE.exec(line)![1].length;
      const { block, next } = parseList(indent);
      blocks.push(block);
      i = next;
      continue;
    }

    if (trimmed.startsWith('>')) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) quote.push(lines[i++].trim().replace(/^>\s?/, ''));
      blocks.push({ kind: 'quote', text: quote.join('\n') });
      continue;
    }

    const para: string[] = [trimmed];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !LIST_RE.test(lines[i]) &&
      !/^(#{1,6}\s|```|~~~|\$\$|>|\\\[)/.test(lines[i].trim()) &&
      !(lines[i].includes('|') && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1]))
    ) {
      para.push(lines[i++].trim());
    }
    blocks.push({ kind: 'paragraph', text: para.join(' ') });
  }
  return blocks;
}

function renderTex(tex: string, display: boolean): string | null {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: true, strict: 'ignore', output: 'htmlAndMathml' });
  } catch {
    return null;
  }
}

const INLINE_RE =
  /(\[\d{1,3}\](?:\[\d{1,3}\])*)|(`[^`]+`)|(\$(?!\s)[^$\n]+?(?<!\s)\$)|(\\\((.+?)\\\))|(\*\*[^*]+\*\*|__[^_]+__)|((?<![\w*])\*(?!\s)[^*\n]+?(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)[^_\n]+?(?<!\s)_(?![\w_]))|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))|(~~[^~]+~~)/g;

function renderInline(text: string, ctx: { sources?: Source[]; onCite?: (n: number) => void }, keyBase = 'i'): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  // A fresh regex per call: bold/italic recurse, and a shared /g regex would have its
  // lastIndex reset by the inner call, re-matching the same token forever.
  const re = new RegExp(INLINE_RE.source, 'g');
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = `${keyBase}-${k++}`;
    const [token] = m;
    if (m[1]) {
      const nums = [...token.matchAll(/\[(\d{1,3})\]/g)].map((x) => parseInt(x[1], 10));
      out.push(
        <span key={key} className={styles.citeGroup}>
          {nums.map((n) => (
            <Citation key={n} n={n} source={ctx.sources?.find((s) => s.n === n)} onCite={ctx.onCite} />
          ))}
        </span>,
      );
    } else if (m[2]) {
      out.push(<code key={key} className={styles.inlineCode}>{token.slice(1, -1)}</code>);
    } else if (m[3] || m[4]) {
      const tex = m[3] ? token.slice(1, -1) : m[5];
      const html = renderTex(tex, false);
      out.push(
        html ? (
          <span key={key} className={styles.inlineMath} dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code key={key} className={styles.inlineCode}>{tex}</code>
        ),
      );
    } else if (m[6]) {
      out.push(<strong key={key}>{renderInline(token.slice(2, -2), ctx, key)}</strong>);
    } else if (m[7]) {
      out.push(<em key={key}>{renderInline(token.slice(1, -1), ctx, key)}</em>);
    } else if (m[8]) {
      out.push(
        <a key={key} href={m[10]} target="_blank" rel="noreferrer noopener">
          {m[9]}
        </a>,
      );
    } else if (m[11]) {
      out.push(<del key={key}>{token.slice(2, -2)}</del>);
    }
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={styles.codeBlock}>
      <div className={styles.codeHeader}>
        <span>{lang || 'text'}</span>
        <button
          type="button"
          className="icon-btn icon-btn-sm"
          aria-label={copied ? 'Copied' : 'Copy code'}
          onClick={() => {
            navigator.clipboard?.writeText(code).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.75} />}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function Markdown({ text, sources, onCite }: MarkdownProps) {
  const blocks = useMemo(() => parseBlocks(text || ''), [text]);
  const ctx = { sources, onCite };

  const renderBlock = (b: Block, i: number | string): ReactNode => {
    const key = `b-${i}`;
    switch (b.kind) {
      case 'heading': {
        const Tag = (b.level <= 2 ? 'h2' : b.level === 3 ? 'h3' : 'h4') as 'h2' | 'h3' | 'h4';
        return <Tag key={key}>{renderInline(b.text, ctx, key)}</Tag>;
      }
      case 'paragraph':
        return <p key={key}>{renderInline(b.text, ctx, key)}</p>;
      case 'list': {
        const items = b.items.map((it, j) => (
          <li key={j}>
            {renderInline(it.text, ctx, `${key}-${j}`)}
            {it.children.map((c, ci) => renderBlock(c, `${i}-${j}-${ci}`))}
          </li>
        ));
        return b.ordered ? (
          <ol key={key} start={b.start}>
            {items}
          </ol>
        ) : (
          <ul key={key}>{items}</ul>
        );
      }
      case 'code':
        return <CodeBlock key={key} lang={b.lang} code={b.code} />;
      case 'math': {
        const html = renderTex(b.tex, true);
        return html ? (
          <div key={key} className={styles.displayMath} dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <pre key={key} className={styles.mathFallback}>{b.tex}</pre>
        );
      }
      case 'quote':
        return (
          <blockquote key={key}>
            {b.text.split('\n').map((l, j) => (
              <Fragment key={j}>
                {renderInline(l, ctx, `${key}-${j}`)}
                <br />
              </Fragment>
            ))}
          </blockquote>
        );
      case 'table':
        return (
          <div key={key} className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  {b.header.map((h, j) => (
                    <th key={j} style={{ textAlign: b.align[j] || 'left' }}>
                      {renderInline(h, ctx, `${key}-h${j}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri}>
                    {r.map((c, ci) => (
                      <td key={ci} style={{ textAlign: b.align[ci] || 'left' }}>
                        {renderInline(c, ctx, `${key}-${ri}-${ci}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case 'rule':
        return <hr key={key} />;
      default:
        return null;
    }
  };

  return <div className={styles.prose}>{blocks.map((b, i) => renderBlock(b, i))}</div>;
}
