import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Megaphone, RefreshCw, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import type { AdminOverview, User } from '../../api';
import { ModelChoices } from '../ModelPicker';
import { useToast } from '../ui/Toast';
import { ViewFrame } from './ViewFrame';
import styles from './views.module.css';

interface AdminViewProps {
  user: User | null;
  accountsMode: boolean;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  /** Reloads the signed-in user after the role is claimed. */
  onBecameAdmin: () => void;
}

function ClaimForm({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.claimAdmin(code.trim());
      toast('You are now the administrator of this server', 'good');
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className={styles.form} onSubmit={submit}>
      <p className={styles.note}>
        The server prints a setup code to its log when it starts, until someone claims the role: on ClawCloud, open the app’s
        Logs; on your own machine, the terminal running <code>server.py</code>. Or set <code>OMNIDOC_ADMIN_CODE</code>, or list
        your e-mail in <code>OMNIDOC_ADMIN_EMAILS</code>.
      </p>
      <label className="field-label" htmlFor="admin-code">Setup code</label>
      <input id="admin-code" className="field" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off"
        spellCheck={false} placeholder="xxxxxx-xxxxxx-xxxxxx" />
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="submit" className="btn btn-primary" disabled={busy || code.trim().length < 4}>
          {busy ? <span className="spinner" /> : <ShieldCheck size={15} strokeWidth={1.75} />} Become the administrator
        </button>
      </div>
    </form>
  );
}

function Announce() {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.announce(title.trim(), body.trim(), url.trim() || undefined);
      toast('Posted to everyone’s notifications', 'good');
      setTitle('');
      setBody('');
      setUrl('');
    } catch (err) {
      toast((err as Error).message, 'bad');
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className={styles.form} onSubmit={submit}>
      <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Title, e.g. New: a Tables tab"
        aria-label="Announcement title" />
      <textarea className="field" value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} rows={3}
        placeholder="What changed, in a sentence or two" aria-label="Announcement text" />
      <input className="field" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Link (optional)" aria-label="Link" />
      <div className={styles.actions}>
        <button type="submit" className="btn btn-primary" disabled={busy || !title.trim()}>
          {busy ? <span className="spinner" /> : <Megaphone size={15} strokeWidth={1.75} />} Post to everyone
        </button>
      </div>
    </form>
  );
}

/** The administrator's view of the server: usage, health, the default model and announcements. */
export function AdminView({ user, accountsMode, sidebarOpen, onOpenSidebar, onBecameAdmin }: AdminViewProps) {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const admin = !accountsMode || !!user?.admin;

  useEffect(() => {
    if (!admin) return;
    let live = true;
    api.adminOverview().then((d) => live && setData(d)).catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [admin, nonce]);

  if (!admin) {
    return (
      <ViewFrame title="Admin" description="Run this server: usage, health, the default model and announcements to every account."
        sidebarOpen={sidebarOpen} onOpenSidebar={onOpenSidebar}>
        {user?.kind === 'guest' ? <p className={styles.note}>Sign in with an account to administer this server.</p> : <ClaimForm onDone={onBecameAdmin} />}
      </ViewFrame>
    );
  }

  const s = data?.stats;
  const h = data?.health;
  // Thirty slots, today last: days without questions stay as empty slots.
  const days = Array.from({ length: 30 }, (_, i) => {
    const day = new Date(Date.now() - (29 - i) * 86_400_000).toISOString().slice(0, 10);
    const found = s?.by_day.find((d) => d.day === day);
    return { day, questions: found?.questions ?? 0, uploads: found?.uploads ?? 0 };
  });
  const peak = Math.max(1, ...days.map((d) => d.questions));
  const memShare = h?.memory_limit_mb ? h.memory_mb / h.memory_limit_mb : null;

  return (
    <ViewFrame
      title="Admin"
      description="This server at a glance: who uses it, how much, and how it is running."
      sidebarOpen={sidebarOpen}
      onOpenSidebar={onOpenSidebar}
      wide
      actions={<button type="button" className="btn btn-secondary btn-sm" onClick={() => setNonce((n) => n + 1)}><RefreshCw size={14} strokeWidth={1.75} /> Refresh</button>}
    >
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {!data && !error && <p className={styles.note}>Loading…</p>}
      {s && h && data && (
        <>
          <div className={styles.tiles}>
            <div className={styles.tile}><span>Accounts</span><strong>{s.accounts}</strong><small>{s.active_30d} asked a question in 30 days</small></div>
            <div className={styles.tile}><span>Questions today</span><strong>{s.questions_today}</strong><small>{s.questions_7d} in 7 days</small></div>
            <div className={styles.tile}><span>Questions, 30 days</span><strong>{s.questions_30d}</strong><small>{s.uploads_30d} uploads</small></div>
            <div className={styles.tile}><span>Documents</span><strong>{s.documents}</strong><small>{s.chats} conversations, {s.guests} demo visits</small></div>
          </div>

          <section className={styles.section}>
            <h2>Questions per day</h2>
            {s.by_day.length ? (
              <div className={styles.bars} role="img" aria-label={`Questions per day over the last 30 days, at most ${peak} in a day`}>
                {days.map((d) => (
                  <span key={d.day} style={{ height: `${(d.questions / peak) * 100}%` }} title={`${d.day}: ${d.questions} questions, ${d.uploads} uploads`} />
                ))}
              </div>
            ) : <p className={styles.note}>No questions in the last 30 days.</p>}
          </section>

          <section className={styles.section}>
            <h2>Server</h2>
            <dl className={styles.facts}>
              <dt>Status</dt>
              <dd><span className={styles.badge} data-tone={h.status === 'healthy' ? 'good' : 'bad'}>{h.status}</span></dd>
              <dt>Memory</dt>
              <dd>
                {h.memory_mb.toLocaleString()} MB{h.memory_limit_mb ? ` of ${h.memory_limit_mb.toLocaleString()} MB` : ''}
                {memShare != null && (
                  <div className={styles.meter} data-warn={memShare > 0.85 || undefined} style={{ marginTop: 6, maxWidth: 320 }}>
                    <span style={{ width: `${Math.min(100, memShare * 100)}%` }} />
                  </div>
                )}
              </dd>
              <dt>Stores</dt>
              <dd>{Object.entries(h.stores).map(([k, v]) => `${k}: ${v}`).join(', ')}</dd>
              <dt>Model providers</dt>
              <dd>{h.providers.length ? h.providers.join(', ') : 'None with a key'}{h.ollama ? ', Ollama' : ''}</dd>
              <dt>Version</dt>
              <dd>{data.settings.version}</dd>
              <dt>Accounts and demo</dt>
              <dd>
                {data.settings.accounts ? 'Accounts on' : 'Local install (no accounts)'}
                {data.settings.demo ? ', demo on' : ''}, {data.settings.trial_answers} free answers per account
              </dd>
            </dl>
          </section>

          <section className={styles.section}>
            <h2>Default model for everyone</h2>
            <p className={styles.note}>Used by everyone who has not picked a model of their own in the model picker.</p>
            <div style={{ padding: 4, borderRadius: 'var(--radius-lg)', boxShadow: 'inset 0 0 0 1px var(--border)', maxWidth: 560 }}>
              <ModelChoices mode="default" />
            </div>
          </section>

          {data.settings.accounts && (
            <section className={styles.section}>
              <h2>Announce something</h2>
              <p className={styles.note}>It appears under Notifications for every account.</p>
              <Announce />
            </section>
          )}

          {data.settings.accounts && (
            <section className={styles.section}>
              <h2>Administrators</h2>
              <ul className={styles.list} style={{ maxWidth: 560 }}>
                {data.admins.map((a) => (
                  <li key={a.id} className={styles.row}>
                    <span className={styles.rowMain}><strong>{a.name}</strong><span>{a.email || 'Passkey account'}</span></span>
                    <span className={styles.badge} data-tone="accent">Setup code</span>
                  </li>
                ))}
                {data.admin_emails.map((e) => (
                  <li key={e} className={styles.row}>
                    <span className={styles.rowMain}><strong>{e}</strong><span>From OMNIDOC_ADMIN_EMAILS</span></span>
                    <span className={styles.badge} data-tone="muted">E-mail</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </ViewFrame>
  );
}
