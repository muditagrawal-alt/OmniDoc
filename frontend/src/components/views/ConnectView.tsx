import { useEffect, useState } from 'react';
import { Check, Copy, Download, KeyRound, Trash2 } from 'lucide-react';
import { api } from '../../api';
import type { DeviceSession, User } from '../../api';
import { Segmented } from '../ui/Controls';
import { useToast } from '../ui/Toast';
import { ViewFrame } from './ViewFrame';
import styles from './views.module.css';

const RAW = 'https://raw.githubusercontent.com/muditagrawal-alt/OmniDoc/main/mcp_server.py';
const TOKEN_LABEL = 'API token: ';

type Client = 'code' | 'desktop' | 'cursor';

function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard refused: the text stays selectable */
    }
  };
  return (
    <pre className={styles.code}>
      {text}
      <button type="button" className={`icon-btn icon-btn-sm ${styles.copy}`} onClick={copy} aria-label="Copy">
        {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.75} />}
      </button>
    </pre>
  );
}

interface ConnectViewProps {
  accountsMode: boolean;
  user: User | null;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
}

/** Use the library from Claude Code, Claude Desktop or Cursor through OmniDoc's MCP server. */
export function ConnectView({ accountsMode, user, sidebarOpen, onOpenSidebar }: ConnectViewProps) {
  const toast = useToast();
  const [client, setClient] = useState<Client>('code');
  const [name, setName] = useState('Claude Code');
  const [token, setToken] = useState<string | null>(null);
  const [tokens, setTokens] = useState<DeviceSession[]>([]);
  const [busy, setBusy] = useState(false);
  const guest = user?.kind === 'guest';
  const needsToken = accountsMode;
  const origin = window.location.origin;
  const path = '/path/to/mcp_server.py';
  const tokenValue = token || '<your token>';

  const loadTokens = () => {
    if (!accountsMode || !user || guest) return;
    api.listSessions().then((s) => setTokens(s.filter((x) => x.device.startsWith(TOKEN_LABEL)))).catch(() => undefined);
  };
  useEffect(loadTokens, [accountsMode, user, guest]);

  const create = async () => {
    setBusy(true);
    try {
      const r = await api.createToken(name.trim() || 'API token');
      setToken(r.token);
      loadTokens();
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    try {
      await api.endSession(id);
      toast('The token no longer works', 'good');
      loadTokens();
    } catch (e) {
      toast((e as Error).message, 'bad');
    }
  };

  const env: Record<string, string> = needsToken
    ? { OMNIDOC_API_URL: origin, OMNIDOC_API_TOKEN: tokenValue }
    : origin.endsWith(':8000') && /localhost|127\.0\.0\.1/.test(origin) ? {} : { OMNIDOC_API_URL: origin };
  const envFlags = Object.entries(env).map(([k, v]) => ` -e ${k}=${v}`).join('');
  const json = JSON.stringify({ mcpServers: { omnidoc: { command: 'python3', args: [path], ...(Object.keys(env).length ? { env } : {}) } } }, null, 2);
  const setup: Record<Client, { where: string; text: string }> = {
    code: { where: 'Run this in a terminal:', text: `claude mcp add omnidoc${envFlags} -- python3 ${path}` },
    desktop: { where: 'Add this to claude_desktop_config.json (Settings, Developer, Edit config), then restart Claude:', text: json },
    cursor: { where: 'Add this to ~/.cursor/mcp.json, then reload Cursor:', text: json },
  };

  return (
    <ViewFrame
      title="Connect"
      description="Use your library from Claude Code, Claude Desktop or Cursor. The assistant can search it, ask cited questions, read documents, extract fields, find sensitive data and compare two documents."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
    >
      {guest ? (
        <p className={styles.note}>The demo library is shared and read-only. Sign in to connect your own library.</p>
      ) : (
        <ol className={styles.steps}>
          <li className={styles.step}>
            <div className={styles.stepBody}>
              <h3>Get the connector</h3>
              <p>One Python file with nothing to install. Save it anywhere, and use its path below.</p>
              <CopyBlock text={`curl -O ${RAW}`} />
              <div className={styles.actions}>
                <a className="btn btn-secondary btn-sm" href={RAW} target="_blank" rel="noreferrer">
                  <Download size={14} strokeWidth={1.75} /> mcp_server.py
                </a>
              </div>
            </div>
          </li>

          {needsToken && (
            <li className={styles.step}>
              <div className={styles.stepBody}>
                <h3>Create an API token</h3>
                <p>The token signs in as you for a year. Keep it secret, like a password; revoke it here or under Devices.</p>
                <div className={styles.tokenRow}>
                  <input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} aria-label="Token name"
                    placeholder="What will use it" />
                  <button type="button" className="btn btn-primary" onClick={create} disabled={busy || !name.trim()}>
                    {busy ? <span className="spinner" /> : <KeyRound size={15} strokeWidth={1.75} />} Create token
                  </button>
                </div>
                {token && (
                  <>
                    <p className={styles.note}>Copy it now: it is not shown again. It is already filled in below.</p>
                    <CopyBlock text={token} />
                  </>
                )}
                {tokens.length > 0 && (
                  <ul className={styles.list}>
                    {tokens.map((t) => (
                      <li key={t.id} className={styles.row}>
                        <span className={styles.rowMain}>
                          <strong>{t.device.slice(TOKEN_LABEL.length)}</strong>
                          <span>{t.last_used_at ? `Last used ${new Date(t.last_used_at * 1000).toLocaleDateString()}` : 'Not used yet'}</span>
                        </span>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => revoke(t.id)}>
                          <Trash2 size={14} strokeWidth={1.75} /> Revoke
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          )}

          <li className={styles.step}>
            <div className={styles.stepBody}>
              <h3>Add it to your assistant</h3>
              <Segmented<Client> label="Assistant" value={client} onChange={setClient}
                options={[{ value: 'code', label: 'Claude Code' }, { value: 'desktop', label: 'Claude Desktop' }, { value: 'cursor', label: 'Cursor' }]} />
              <p>{setup[client].where} Replace <code>{path}</code> with where you saved the file.</p>
              <CopyBlock text={setup[client].text} />
            </div>
          </li>

          <li className={styles.step}>
            <div className={styles.stepBody}>
              <h3>Ask your assistant</h3>
              <p>For example: “Search my OmniDoc library for the Northwind contract’s payment terms”, or “Use OmniDoc to compare the 2024 and 2025 annual reports.”</p>
            </div>
          </li>
        </ol>
      )}
    </ViewFrame>
  );
}
