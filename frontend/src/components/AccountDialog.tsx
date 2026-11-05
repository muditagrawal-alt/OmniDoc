import { useCallback, useEffect, useState } from 'react';
import { Download, KeyRound, LogOut, Monitor, ShieldCheck, Smartphone, Trash2 } from 'lucide-react';
import { api } from '../api';
import type { AccountInfo, AuthMethods, DeviceSession, Passkey, TotpSetup } from '../api';
import { passkeysSupported } from '../lib/webauthn';
import { Dialog } from './ui/Dialog';
import { RecoveryCodes } from './SignIn';
import styles from './AccountDialog.module.css';

interface AccountDialogProps {
  open: boolean;
  methods: AuthMethods;
  onClose: () => void;
  onSignOut: () => void;
  onDeleted: () => void;
}

type Tab = 'overview' | 'security' | 'devices';

const PROVIDERS: Record<string, string> = {
  email: 'an e-mailed code', google: 'Google', github: 'GitHub', passkey: 'a passkey', guest: 'the demo', local: 'a local profile',
};

function ago(seconds?: number | null): string {
  if (!seconds) return 'never';
  const diff = Date.now() / 1000 - seconds;
  if (diff < 90) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)} minutes ago`;
  if (diff < 86400 * 2) return `${Math.round(diff / 3600)} hours ago`;
  return new Date(seconds * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

interface Loaded {
  account: AccountInfo;
  keys?: Passkey[];
  sessions?: DeviceSession[];
}

async function load(): Promise<Loaded> {
  const account = await api.getAccount();
  if (!account.accounts || account.guest) return { account };
  const [keys, sessions] = await Promise.all([api.listPasskeys(), api.listSessions()]);
  return { account, keys, sessions };
}

function Meter({ label, used, limit, unit = '' }: { label: string; used: number; limit: number; unit?: string }) {
  const share = Math.min(1, limit ? used / limit : 0);
  return (
    <div className={styles.meter}>
      <div className={styles.meterRow}>
        <span>{label}</span>
        <span className={styles.figures}>
          {used.toLocaleString()}{unit} of {limit.toLocaleString()}{unit}
        </span>
      </div>
      <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used} className={styles.track}>
        <div className={styles.fill} data-full={share > 0.9 || undefined} style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  );
}

/**
 * The signed-in account: usage against the server's limits; passkeys, linked GitHub or Google, the
 * authenticator app and recovery codes; signed-in devices; exporting and deleting everything.
 */
export function AccountDialog({ open, methods, onClose, onSignOut, onDeleted }: AccountDialogProps) {
  const [tab, setTab] = useState<Tab>('overview');
  const [info, setInfo] = useState<AccountInfo | null>(null);
  const [keys, setKeys] = useState<Passkey[]>([]);
  const [sessions, setSessions] = useState<DeviceSession[]>([]);
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState('');
  const [disabling, setDisabling] = useState(false);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');

  const apply = useCallback((data: Loaded) => {
    setInfo(data.account);
    if (data.keys) setKeys(data.keys);
    if (data.sessions) setSessions(data.sessions);
  }, []);
  const refresh = async () => apply(await load());

  // The dialog is remounted each time it opens (see App), so its state starts fresh.
  useEffect(() => {
    if (!open) return;
    load().then(apply).catch((e: Error) => setError(e.message));
  }, [open, apply]);

  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const spin = (label: string) => (busy === label ? <span className="spinner" /> : null);
  const mb = (bytes: number) => Math.round((bytes / (1024 * 1024)) * 10) / 10;
  const hosted = !!info?.accounts && !info.guest;
  const security = info?.security;
  const email = security?.email || '';

  const overview = info && (
    <>
      {info.guest ? (
        <div className={styles.callout}>
          <strong>You are trying the demo.</strong>
          <span>The sample library is shared and read-only, and this guest session ends after a day. Sign in to upload your own documents and keep your conversations.</span>
          <button type="button" className="btn btn-primary btn-sm" onClick={onSignOut}>Sign in or create an account</button>
        </div>
      ) : (
        <p className={styles.lede}>
          Signs in with {PROVIDERS[info.user.provider] || info.user.provider}
          {email && info.user.provider === 'passkey' ? ` or ${email}` : ''}
          {info.admin ? ' · administrator' : ''}
        </p>
      )}
      {info.limits ? (
        <section className={styles.section}>
          <h3>Today</h3>
          <Meter label="Questions" used={info.usage.questions} limit={info.limits.questions_per_day} />
          {!info.guest && <Meter label="Uploads" used={info.usage.uploads} limit={info.limits.uploads_per_day} />}
          {!info.guest && <Meter label="Library storage" used={mb(info.storage_bytes)} limit={info.limits.storage_mb} unit=" MB" />}
          <p className={styles.note}>Daily limits reset at midnight UTC. They keep the free model quotas shared fairly.</p>
        </section>
      ) : (
        <p className={styles.note}>{mb(info.storage_bytes)} MB in your library. No limits apply to this account.</p>
      )}
      {hosted && (
        <section className={styles.section}>
          <h3>Your data</h3>
          <p className={styles.note}>Every document you uploaded, every conversation (as Markdown and JSON) and your account record, in one zip.</p>
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy} onClick={() => act('export', () => api.exportAccount())}>
              {spin('export') || <Download size={14} strokeWidth={1.75} />} Download everything
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(true)} disabled={confirming}>
              <Trash2 size={14} strokeWidth={1.75} /> Delete account…
            </button>
          </div>
          {confirming && (
            <div className={styles.danger}>
              <p>This permanently deletes your documents, their indexes and your conversations. Type <strong>delete</strong> to confirm.</p>
              <input className="field" value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Type delete to confirm" autoComplete="off" />
              <button type="button" className="btn btn-danger btn-sm" disabled={typed.trim().toLowerCase() !== 'delete' || !!busy}
                onClick={() => act('delete', async () => { await api.deleteAccount(); onDeleted(); })}>
                {spin('delete')} Delete my account and data
              </button>
            </div>
          )}
        </section>
      )}
    </>
  );

  const securityTab = info && security && (
    <>
      <section className={styles.section}>
        <h3>Passkeys</h3>
        <p className={styles.note}>Sign in with Face ID, Touch ID, Windows Hello, your phone or a security key. Nothing to remember or type.</p>
        <ul className={styles.list}>
          {keys.map((k) => (
            <li key={k.id}>
              <KeyRound size={16} strokeWidth={1.75} className={styles.icon} />
              <div className={styles.itemText}>
                <span>{k.label || 'Passkey'}</span>
                <span className={styles.meta}>Added {ago(k.created_at)} · last used {ago(k.last_used_at)}</span>
              </div>
              <button type="button" className="icon-btn icon-btn-sm" aria-label={`Remove ${k.label || 'passkey'}`} disabled={!!busy}
                onClick={() => act(`rm-${k.id}`, async () => { setKeys(await api.removePasskey(k.id)); await refresh(); })}>
                {spin(`rm-${k.id}`) || <Trash2 size={14} strokeWidth={1.75} />}
              </button>
            </li>
          ))}
          {!keys.length && <li className={styles.empty}>No passkeys yet.</li>}
        </ul>
        {methods.passkey && passkeysSupported() && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
            onClick={() => act('add', async () => {
              const result = await api.addPasskey();
              setKeys(result.passkeys);
              if (result.recovery_codes) setNewCodes(result.recovery_codes);
              await refresh();
            })}>
            {spin('add') || <KeyRound size={14} strokeWidth={1.75} />} Add a passkey on this device
          </button>
        )}
      </section>

      {(methods.github || methods.google) && (
        <section className={styles.section}>
          <h3>Linked sign-in</h3>
          {email ? (
            <p className={styles.note}>You can also sign in with {methods.github ? 'GitHub' : 'Google'}{methods.github && methods.google ? ' or Google' : ''} as <strong>{email}</strong>.</p>
          ) : (
            <>
              <p className={styles.note}>Link GitHub or Google as a second way in, in case you lose your passkeys.</p>
              <div className={styles.actions}>
                {(['github', 'google'] as const).filter((p) => methods[p]).map((p) => (
                  <button key={p} type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
                    onClick={() => act(`link-${p}`, async () => { window.location.href = await api.linkUrl(p); })}>
                    {spin(`link-${p}`)} Link {p === 'github' ? 'GitHub' : 'Google'}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      <section className={styles.section}>
        <h3>
          Authenticator app
          {security.totp && <span className={styles.on}><ShieldCheck size={13} strokeWidth={2} /> On</span>}
        </h3>
        <p className={styles.note}>
          {security.totp
            ? 'Signing in with GitHub, Google or an e-mailed code also asks for a code from your app. Passkeys need no code.'
            : 'Ask for a six-digit code from an app such as Google Authenticator, Microsoft Authenticator or 1Password after GitHub, Google or e-mail sign-in.'}
        </p>
        {!security.totp && !setup && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
            onClick={() => act('setup', async () => { setSetup(await api.totpSetup()); setCode(''); })}>
            {spin('setup') || <Smartphone size={14} strokeWidth={1.75} />} Set up an authenticator app
          </button>
        )}
        {setup && (
          <div className={styles.setup}>
            <div className={styles.qr} dangerouslySetInnerHTML={{ __html: setup.qr_svg }} aria-label="QR code for your authenticator app" role="img" />
            <div className={styles.setupText}>
              <p className={styles.note}>Scan the code with your app, or enter this key:</p>
              <code className={styles.secret}>{setup.secret.match(/.{1,4}/g)?.join(' ')}</code>
              <label className="field-label" htmlFor="totp-code">Code from the app</label>
              <input id="totp-code" className={`field ${styles.digits}`} inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
              <div className={styles.actions}>
                <button type="button" className="btn btn-primary btn-sm" disabled={code.length !== 6 || !!busy}
                  onClick={() => act('enable', async () => {
                    const result = await api.totpEnable(setup.challenge_id, code);
                    setSetup(null);
                    if (result.recovery_codes) setNewCodes(result.recovery_codes);
                    await refresh();
                  })}>
                  {spin('enable')} Turn on
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSetup(null)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
        {security.totp && !disabling && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setDisabling(true); setCode(''); }}>Turn off…</button>
        )}
        {security.totp && disabling && (
          <div className={styles.inline}>
            <input className={`field ${styles.digits}`} aria-label="A current code or a recovery code" placeholder="Code" maxLength={20}
              value={code} onChange={(e) => setCode(e.target.value)} />
            <button type="button" className="btn btn-secondary btn-sm" disabled={code.trim().length < 6 || !!busy}
              onClick={() => act('disable', async () => { await api.totpDisable(code.trim()); setDisabling(false); await refresh(); })}>
              {spin('disable')} Turn off
            </button>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h3>Recovery codes</h3>
        <p className={styles.note}>
          {security.recovery_codes_left} of 10 left. Each code signs in once if you lose your passkeys, or replaces an authenticator code.
        </p>
        {newCodes ? (
          <>
            <RecoveryCodes codes={newCodes} />
            <p className={styles.note}>Save these now: they are not shown again, and older codes no longer work.</p>
          </>
        ) : (
          <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
            onClick={() => act('codes', async () => { setNewCodes(await api.newRecoveryCodes()); await refresh(); })}>
            {spin('codes')} Make new codes
          </button>
        )}
      </section>
    </>
  );

  const devicesTab = (
    <section className={styles.section}>
      <h3>Signed-in devices</h3>
      <ul className={styles.list}>
        {sessions.map((s) => (
          <li key={s.id}>
            <Monitor size={16} strokeWidth={1.75} className={styles.icon} />
            <div className={styles.itemText}>
              <span>{s.device}{s.current && <span className={styles.current}>This device</span>}</span>
              <span className={styles.meta}>Active {ago(s.last_used_at)}{s.ip ? ` · ${s.ip}` : ''}</span>
            </div>
            {!s.current && (
              <button type="button" className="btn btn-ghost btn-sm" disabled={!!busy}
                onClick={() => act(`end-${s.id}`, async () => { await api.endSession(s.id); setSessions(await api.listSessions()); })}>
                {spin(`end-${s.id}`)} Sign out
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className={styles.actions}>
        {sessions.length > 1 && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
            onClick={() => act('others', async () => { await api.endOtherSessions(); setSessions(await api.listSessions()); })}>
            {spin('others')} Sign out of all other devices
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onSignOut}>
          <LogOut size={14} strokeWidth={1.75} /> Sign out here
        </button>
      </div>
    </section>
  );

  const title = info?.guest ? 'Demo' : 'Account';
  const description = info ? (info.guest ? 'Guest session' : info.user.email || info.user.name) : undefined;

  return (
    <Dialog open={open} onClose={onClose} title={title} description={description} width={560}>
      {hosted && (
        <div role="tablist" aria-label="Account sections" className={styles.tabs}>
          {([['overview', 'Overview'], ['security', 'Sign-in and security'], ['devices', 'Devices']] as const).map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} className={styles.tab} onClick={() => { setTab(key); setError(null); }}>
              {label}
            </button>
          ))}
        </div>
      )}
      <div role={hosted ? 'tabpanel' : undefined}>
        {(!hosted || tab === 'overview') && overview}
        {hosted && tab === 'security' && securityTab}
        {hosted && tab === 'devices' && devicesTab}
        {!hosted && info && !info.guest && (
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onSignOut}>Sign out</button>
          </div>
        )}
      </div>
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </Dialog>
  );
}
