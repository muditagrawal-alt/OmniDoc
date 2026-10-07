import React, { useState } from 'react';
import { Copy, Check, Network, FileText } from 'lucide-react';
import katex from 'katex';

interface MarkdownRendererProps {
  content: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  if (!content) return null;

  // Split lines
  const rawLines = content.split('\n');
  const blocks: React.ReactNode[] = [];

  let inCodeBlock = false;
  let codeBlockLang = '';
  let codeBlockLines: string[] = [];

  let currentListItems: { ordered: boolean; text: string }[] = [];
  let currentListOrdered = false;

  let inTable = false;
  let tableHeader: string[] = [];
  let tableRows: string[][] = [];

  const flushList = () => {
    if (currentListItems.length > 0) {
      const items = [...currentListItems];
      const ordered = currentListOrdered;
      currentListItems = [];
      blocks.push(
        <div key={`list-${blocks.length}`} style={{ margin: '0.65rem 0 0.85rem 0', paddingLeft: '0.2rem' }}>
          {items.map((item, idx) => (
            <div key={idx} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '0.65rem',
              marginBottom: '0.45rem',
              lineHeight: 1.68,
              fontSize: '0.94rem',
              color: 'var(--text-primary)'
            }}>
              {ordered ? (
                <span style={{
                  fontSize: '0.8rem',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--accent-primary)',
                  fontWeight: 600,
                  minWidth: '20px',
                  lineHeight: '1.68'
                }}>
                  {idx + 1}.
                </span>
              ) : (
                <span style={{
                  display: 'inline-block',
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--accent-primary)',
                  marginTop: '0.58rem',
                  flexShrink: 0,
                  boxShadow: '0 0 6px rgba(59, 130, 246, 0.6)'
                }} />
              )}
              <div style={{ flex: 1, wordBreak: 'break-word' }}>
                {renderInlineFormatted(item.text)}
              </div>
            </div>
          ))}
        </div>
      );
    }
  };

  const flushTable = () => {
    if (inTable && tableHeader.length > 0) {
      const header = [...tableHeader];
      const rows = [...tableRows];
      tableHeader = [];
      tableRows = [];
      inTable = false;

      blocks.push(
        <div key={`table-${blocks.length}`} style={{
          margin: '0.85rem 0',
          overflowX: 'auto',
          borderRadius: 'var(--radius-md)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          backgroundColor: '#0b101b'
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
            <thead>
              <tr style={{ backgroundColor: 'rgba(255, 255, 255, 0.04)', borderBottom: '1px solid rgba(255, 255, 255, 0.1)' }}>
                {header.map((col, idx) => (
                  <th key={idx} style={{
                    padding: '0.6rem 0.85rem',
                    fontWeight: 650,
                    color: '#93c5fd',
                    letterSpacing: '0.02em',
                    fontSize: '0.82rem',
                    textTransform: 'uppercase'
                  }}>
                    {renderInlineFormatted(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr key={rowIdx} style={{
                  borderBottom: rowIdx === rows.length - 1 ? 'none' : '1px solid rgba(255, 255, 255, 0.04)',
                  backgroundColor: rowIdx % 2 === 1 ? 'rgba(255, 255, 255, 0.015)' : 'transparent'
                }}>
                  {row.map((cell, cellIdx) => (
                    <td key={cellIdx} style={{
                      padding: '0.55rem 0.85rem',
                      color: 'var(--text-primary)',
                      lineHeight: 1.5
                    }}>
                      {renderInlineFormatted(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  };

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i];
    const trimmed = line.trim();

    // Check code blocks ```
    if (trimmed.startsWith('```')) {
      flushList();
      flushTable();
      if (inCodeBlock) {
        const codeText = codeBlockLines.join('\n');
        blocks.push(
          <CodeBlockItem key={`code-${blocks.length}`} code={codeText} language={codeBlockLang} />
        );
        inCodeBlock = false;
        codeBlockLines = [];
        codeBlockLang = '';
      } else {
        inCodeBlock = true;
        codeBlockLang = trimmed.slice(3).trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Empty line -> flush open collections
    if (!trimmed) {
      flushList();
      flushTable();
      continue;
    }

    // Markdown Table Detection (| col1 | col2 |)
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      flushList();
      const cells = trimmed
        .split('|')
        .slice(1, -1)
        .map(c => c.trim());

      // If it's a separator line (|---|---|), ignore and mark inTable true
      if (cells.every(c => /^:?-+:?$/.test(c))) {
        inTable = true;
        continue;
      }

      if (!inTable && tableHeader.length === 0) {
        tableHeader = cells;
        inTable = true;
      } else {
        tableRows.push(cells);
      }
      continue;
    } else if (inTable) {
      flushTable();
    }

    // Heading 1 (#)
    if (trimmed.startsWith('# ')) {
      flushList();
      blocks.push(
        <h1 key={`h1-${blocks.length}`} style={{
          fontSize: '1.35rem',
          fontWeight: 700,
          color: '#ffffff',
          margin: '1.25rem 0 0.6rem 0',
          letterSpacing: '-0.02em',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          paddingBottom: '0.4rem'
        }}>
          {renderInlineFormatted(cleanPrefix(trimmed.slice(2)))}
        </h1>
      );
      continue;
    }

    // Heading 2 (##)
    if (trimmed.startsWith('## ')) {
      flushList();
      blocks.push(
        <h2 key={`h2-${blocks.length}`} style={{
          fontSize: '1.18rem',
          fontWeight: 650,
          color: '#f8fafc',
          margin: '1.1rem 0 0.5rem 0',
          letterSpacing: '-0.015em'
        }}>
          {renderInlineFormatted(cleanPrefix(trimmed.slice(3)))}
        </h2>
      );
      continue;
    }

    // Heading 3 (###)
    if (trimmed.startsWith('### ')) {
      flushList();
      blocks.push(
        <h3 key={`h3-${blocks.length}`} style={{
          fontSize: '1.02rem',
          fontWeight: 600,
          color: '#93c5fd',
          margin: '0.9rem 0 0.4rem 0'
        }}>
          {renderInlineFormatted(cleanPrefix(trimmed.slice(4)))}
        </h3>
      );
      continue;
    }

    // Blockquote (> )
    if (trimmed.startsWith('> ')) {
      flushList();
      blocks.push(
        <div key={`quote-${blocks.length}`} style={{
          borderLeft: '3px solid var(--accent-primary)',
          backgroundColor: 'rgba(59, 130, 246, 0.06)',
          padding: '0.65rem 1rem',
          margin: '0.65rem 0',
          borderRadius: '0 8px 8px 0',
          color: 'var(--text-secondary)',
          fontSize: '0.92rem',
          lineHeight: 1.6
        }}>
          {renderInlineFormatted(cleanPrefix(trimmed.slice(2)))}
        </div>
      );
      continue;
    }

    // Unordered List (- or * or •)
    // Also cleans nested prefixes like "- * Point" or "* - Point"
    const unorderedMatch = line.match(/^(\s*)([-*•])\s+(.+)$/);
    if (unorderedMatch) {
      if (currentListItems.length > 0 && currentListOrdered) {
        flushList();
      }
      currentListOrdered = false;
      const cleanItemText = cleanNestedListPrefix(unorderedMatch[3]);
      currentListItems.push({ ordered: false, text: cleanItemText });
      continue;
    }

    // Ordered List (1. )
    const orderedMatch = line.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (orderedMatch) {
      if (currentListItems.length > 0 && !currentListOrdered) {
        flushList();
      }
      currentListOrdered = true;
      const cleanItemText = cleanNestedListPrefix(orderedMatch[3]);
      currentListItems.push({ ordered: true, text: cleanItemText });
      continue;
    }

    // Regular Paragraph
    flushList();
    blocks.push(
      <p key={`p-${blocks.length}`} style={{
        margin: '0 0 0.75rem 0',
        lineHeight: 1.7,
        fontSize: '0.94rem',
        color: 'var(--text-primary)',
        letterSpacing: '-0.005em'
      }}>
        {renderInlineFormatted(cleanPrefix(trimmed))}
      </p>
    );
  }

  flushList();
  flushTable();

  return (
    <div className="editorial-markdown-content" style={{ display: 'flex', flexDirection: 'column' }}>
      {blocks}
    </div>
  );
};

// Component for Code Blocks with Copy button
const CodeBlockItem: React.FC<{ code: string; language: string }> = ({ code, language }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{
      margin: '0.75rem 0',
      borderRadius: 'var(--radius-md)',
      backgroundColor: '#090d16',
      border: '1px solid rgba(255, 255, 255, 0.08)',
      overflow: 'hidden'
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.35rem 0.85rem',
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)'
      }}>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {language || 'text'}
        </span>
        <button
          onClick={handleCopy}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.3rem',
            fontSize: '0.72rem',
            color: copied ? 'var(--accent-emerald)' : 'var(--text-dim)',
            background: 'none',
            border: 'none',
            cursor: 'pointer'
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy code'}</span>
        </button>
      </div>
      <pre style={{
        margin: 0,
        padding: '0.85rem 1rem',
        overflowX: 'auto',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.85rem',
        color: '#e2e8f0',
        lineHeight: 1.55
      }}>
        <code>{code}</code>
      </pre>
    </div>
  );
};

/**
 * Strips awkward nested bullet prefixes like "* ", "- * ", "• " that LLMs sometimes generate
 */
function cleanNestedListPrefix(text: string): string {
  // Strip nested "- * ", "* * ", "• * "
  let cleaned = text.trim();
  cleaned = cleaned.replace(/^([*•\-]\s*)+/, '');
  return cleaned;
}

/**
 * Strips stray leading bullet characters if a paragraph accidentally started with a solitary *
 */
function cleanPrefix(text: string): string {
  // If line starts with a lone asterisk followed by space (e.g. "* Founder of..."), strip it
  if (text.startsWith('* ') && !text.slice(2).includes('*')) {
    return text.slice(2);
  }
  return text;
}

/**
 * Parses inline formatting:
 * - Bold: **text**
 * - Italic: *text* (when properly paired)
 * - Inline code: `code`
 * - KG Triple Citations: [kg_triple: ...] or Source: [kg_triple: ...]
 * - Chunk Citations: [Chunk: ...] or [Entity: ...]
 * - LaTeX Math: $expr$
 * - Completely sanitizes and eliminates raw stray asterisks
 */
function renderInlineFormatted(text: string): React.ReactNode {
  if (!text) return null;

  // 1. First, normalize awkward "Source: [kg_triple: ...]" or "[kg_triple: ...]"
  // Replace "Source: [kg_triple:" with "[kg_triple:" so we don't get redundant "Source:" label
  let normalized = text.replace(/Source:\s*\[kg_triple:/gi, '[kg_triple:');
  normalized = normalized.replace(/Source:\s*\[Chunk:/gi, '[Chunk:');

  const parts: React.ReactNode[] = [];
  let keyIndex = 0;

  // Match:
  // 1. Math: \$([^\$]+)\$
  // 2. KG Triple / Entity: \[(?:kg_triple|Entity):\s*([^\]]+)\]
  // 3. Chunk: \[(?:Chunk):\s*([^\]]+)\]
  // 4. Inline Code: `([^`]+)`
  // 5. Bold: \*\*([^*]+?)\*\*
  // 6. Italic: \*([^*\s][^*]*?[^*\s])\*
  const tokenRegex = /(\$([^\$]+)\$|\[(?:kg_triple|Entity):\s*([^\]]+)\]|\[(?:Chunk):\s*([^\]]+)\]|`([^`]+)`|\*\*([^*]+?)\*\*|\*([^*\s][^*]*?[^*\s])\*)/g;

  let lastIndex = 0;
  let match;

  while ((match = tokenRegex.exec(normalized)) !== null) {
    // Add text before match, sanitizing any lone stray asterisks
    if (match.index > lastIndex) {
      const rawSub = normalized.slice(lastIndex, match.index);
      parts.push(
        <span key={`txt-${keyIndex++}`}>
          {sanitizeStrayAsterisks(rawSub)}
        </span>
      );
    }

    // Math: $expr$
    if (match[2]) {
      const mathExpr = match[2];
      try {
        const html = katex.renderToString(mathExpr, { throwOnError: false });
        parts.push(
          <span
            key={`math-${keyIndex++}`}
            dangerouslySetInnerHTML={{ __html: html }}
            style={{ margin: '0 0.2rem', color: '#67e8f9' }}
          />
        );
      } catch {
        parts.push(<code key={`math-err-${keyIndex++}`}>{mathExpr}</code>);
      }
    }
    // Knowledge Graph citation: [kg_triple: ...] or [Entity: ...]
    else if (match[3]) {
      const entityFact = match[3].replace(/->/g, ' → ');
      parts.push(
        <span
          key={`kg-${keyIndex++}`}
          title="Verified Knowledge Graph Fact"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.3rem',
            fontSize: '0.72rem',
            padding: '0.12rem 0.55rem',
            margin: '0 0.25rem',
            borderRadius: '9999px',
            backgroundColor: 'rgba(59, 130, 246, 0.12)',
            border: '1px solid rgba(59, 130, 246, 0.3)',
            color: '#93c5fd',
            fontFamily: 'var(--font-mono)',
            verticalAlign: 'middle',
            whiteSpace: 'nowrap'
          }}
        >
          <Network size={11} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
          <span>{entityFact}</span>
        </span>
      );
    }
    // Chunk citation: [Chunk: ...]
    else if (match[4]) {
      const chunkId = match[4];
      parts.push(
        <span
          key={`chk-${keyIndex++}`}
          title={`Grounded in Passage: ${chunkId}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            fontSize: '0.72rem',
            padding: '0.12rem 0.5rem',
            margin: '0 0.2rem',
            borderRadius: '9999px',
            backgroundColor: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            color: '#a7f3d0',
            fontFamily: 'var(--font-mono)',
            verticalAlign: 'middle',
            whiteSpace: 'nowrap'
          }}
        >
          <FileText size={10} style={{ color: 'var(--accent-emerald)', flexShrink: 0 }} />
          <span>Doc Ref: {chunkId.slice(0, 10)}</span>
        </span>
      );
    }
    // Inline Code: `code`
    else if (match[5]) {
      parts.push(
        <code
          key={`code-${keyIndex++}`}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.84em',
            padding: '0.15rem 0.4rem',
            backgroundColor: 'rgba(255, 255, 255, 0.08)',
            borderRadius: '4px',
            color: '#93c5fd'
          }}
        >
          {match[5]}
        </code>
      );
    }
    // Bold: **text**
    else if (match[6]) {
      parts.push(
        <strong key={`bold-${keyIndex++}`} style={{ fontWeight: 650, color: '#ffffff' }}>
          {match[6]}
        </strong>
      );
    }
    // Italic: *text*
    else if (match[7]) {
      parts.push(
        <em key={`em-${keyIndex++}`} style={{ fontStyle: 'italic', color: 'var(--text-secondary)' }}>
          {match[7]}
        </em>
      );
    }

    lastIndex = tokenRegex.lastIndex;
  }

  // Trailing text
  if (lastIndex < normalized.length) {
    const trailing = normalized.slice(lastIndex);
    parts.push(
      <span key={`txt-${keyIndex++}`}>
        {sanitizeStrayAsterisks(trailing)}
      </span>
    );
  }

  return <>{parts}</>;
}

/**
 * Strips or cleans up any lone stray asterisk '*' that leaked through
 * (so users never see raw AI asterisk clutter like ' * ' or 'point *')
 */
function sanitizeStrayAsterisks(raw: string): string {
  // Replace lone asterisk surrounded by spaces or at word boundaries with nothing or clean space
  return raw
    .replace(/(^|\s)\*(\s|$)/g, '$1$2')
    .replace(/\*+/g, '') // strip any leftover unpaired asterisks
    .replace(/\s{2,}/g, ' '); // collapse double spaces
}
