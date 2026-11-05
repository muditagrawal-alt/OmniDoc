import { useEffect, useMemo, useState } from 'react';
import { Check, ExternalLink, Eye, EyeOff, KeyRound, Laptop, Server, Trash2 } from 'lucide-react';
import { api } from '../api';
import type { KeyProvider, ServerKey } from '../api';
import { Dialog } from './ui/Dialog';
import styles from './KeysDialog.module.css';

interface KeysDialogProps {
  open: boolean;
  onClose: () => void;
  /** Why the dialog opened on its own (the free answers ran out), shown as a banner. */
  reason?: string | null;
  /** Signed-in accounts may keep a key on the server; guests and local installs keep it on the device. */
  canStoreOnServer: boolean;
  onSaved: () => void;
}

type Where = 'device' | 'server';

/** The headline of a provider's free-tier note ("Free plan: 30 requests/min, 1,000/day"). */
const brief = (note: string) => note.split(/[;(]|\.\s/)[0].trim().replace(/[.:,]$/, '');

/** The server's 402 message as a heading and a line ("You have used your 3 free answers. Add..."). */
function splitReason(reason: string): [string, string] {
  const at = reason.indexOf('. ');
  return at > 0 ? [reason.slice(0, at), reason.slice(at + 2)] : [reason, ''];
}

/**
 * Bring your own key: after the free answers, the user's own free key answers for them. It stays in
 * this browser unless they choose to keep it, encrypted, on the server.
 */
export function KeysDialog({ open, onClose, reason, canStoreOnServer, onSaved }: KeysDialogProps) {
  const [providers, setProviders] = useState<KeyProvider[]>([]);
  const [trial, setTrial] = useState(3);
  const [selected, setSelected] = useState('gemini');
  const [key, setKey] = useState('');
  const [show, setShow] = useState(false);
  const [where, setWhere] = useState<Where>('device');
  const [device, setDevice] = useState<Record<string, string>>(() => api.deviceKeys());
  const [server, setServer] = useState<ServerKey[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // Remounted each time it opens (see App), so its state starts fresh.
  useEffect(() => {
    if (!open) return;
    api.keyProviders().then((d) => { setProviders(d.providers); setTrial(d.trial_answers); }).catch((e: Error) => setError(e.message));
    if (canStoreOnServer) api.serverKeys().then(setServer).catch(() => undefined);
  }, [open, canStoreOnServer]);

  const provider = useMemo(() => providers.find((p) => p.name === selected), [providers, selected]);
  const label = (name: string) => providers.find((p) => p.name === name)?.label || name;

  const save = async () => {
    const value = key.trim();
    if (value.length < 8) {
      setError('Paste the whole key.');
      return;
    }
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      if (where === 'server') {
        setServer(await api.saveServerKey(selected, value));
      } else {
        const check = await api.checkKey(selected, value);
        if (!check.ok) throw new Error(check.reason || 'The key did not work.');
        api.setDeviceKey(selected, value);
        setDevice(api.deviceKeys());
      }
      setKey('');
      setDone(`${label(selected)} key is ready. Your next questions use it.`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeDevice = (name: string) => {
    api.setDeviceKey(name, null);
    setDevice(api.deviceKeys());
    onSaved();
  };

  const removeServer = async (name: string) => {
    try {
      setServer(await api.deleteServerKey(name));
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saved = [
    ...Object.entries(device).map(([name, last4]) => ({ name, last4, where: 'device' as Where })),
    ...server.map((k) => ({ name: k.provider, last4: k.last4, where: 'server' as Where })),
  ];

  return (
    <Dialog open={open} onClose={onClose} title="Your own model key" width={580}
      description="Every provider below has a free tier. Your key answers only your own questions.">
      {reason && (
        <div className={styles.flash} role="status">
          <KeyRound size={18} strokeWidth={1.75} />
          <div>
            <strong>{splitReason(reason)[0]}</strong>
            <span>{splitReason(reason)[1] || 'Add a free key from any provider below to keep going.'}</span>
          </div>
        </div>
      )}
      {!reason && trial > 0 && (
        <p className={styles.lede}>New accounts get {trial} answers on OmniDoc's keys. After that, a free key of your own keeps you going; add more than one and they cover for each other when one is busy.</p>
      )}

      <fieldset className={styles.providers}>
        <legend className="field-label">Provider</legend>
        {providers.map((p) => (
          <label key={p.name} className={styles.provider} data-selected={selected === p.name || undefined}>
            <input type="radio" name="provider" value={p.name} checked={selected === p.name} onChange={() => setSelected(p.name)} />
            <span className={styles.providerName}>
              {p.label}
              {(device[p.name] || server.some((k) => k.provider === p.name)) && <Check size={13} strokeWidth={2.25} aria-label="key saved" />}
            </span>
            <span className={styles.providerNote}>{brief(p.free_note)}</span>
          </label>
        ))}
      </fieldset>

      {provider && (
        <div className={styles.keyRow}>
          <p className={styles.providerDetail}>{provider.free_note}</p>
          <a className={styles.signUp} href={provider.sign_up} target="_blank" rel="noreferrer">
            Get a free {provider.label} key <ExternalLink size={13} strokeWidth={1.75} />
          </a>
          <label className="field-label" htmlFor="own-key">API key</label>
          <div className={styles.inputWrap}>
            <input id="own-key" className={`field ${styles.key}`} type={show ? 'text' : 'password'} autoComplete="off" spellCheck={false}
              placeholder={`Paste your ${provider.label} key`} value={key} onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void save(); }} />
            <button type="button" className="icon-btn icon-btn-sm" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide the key' : 'Show the key'}>
              {show ? <EyeOff size={15} strokeWidth={1.75} /> : <Eye size={15} strokeWidth={1.75} />}
            </button>
          </div>
        </div>
      )}

      <fieldset className={styles.where}>
        <legend className="field-label">Where to keep it</legend>
        <label className={styles.choice} data-selected={where === 'device' || undefined}>
          <input type="radio" name="where" checked={where === 'device'} onChange={() => setWhere('device')} />
          <Laptop size={16} strokeWidth={1.75} />
          <span><strong>This browser only</strong> (recommended). Sent with each of your questions over HTTPS; never stored on the server.</span>
        </label>
        {canStoreOnServer && (
          <label className={styles.choice} data-selected={where === 'server' || undefined}>
            <input type="radio" name="where" checked={where === 'server'} onChange={() => setWhere('server')} />
            <Server size={16} strokeWidth={1.75} />
            <span><strong>Encrypted on the server</strong>. Works on your other devices; remove it any time.</span>
          </label>
        )}
      </fieldset>

      <button type="button" className={`btn btn-primary ${styles.save}`} disabled={busy || !key.trim()} onClick={save}>
        {busy && <span className="spinner" />} Check and use this key
      </button>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {done && <p role="status" className={styles.done}><Check size={14} strokeWidth={2} /> {done}</p>}

      {saved.length > 0 && (
        <section className={styles.saved}>
          <h3>Saved keys</h3>
          <ul>
            {saved.map((k) => (
              <li key={`${k.where}-${k.name}`}>
                {k.where === 'device' ? <Laptop size={15} strokeWidth={1.75} /> : <Server size={15} strokeWidth={1.75} />}
                <span className={styles.savedName}>{label(k.name)}</span>
                <span className={styles.savedMeta}>{k.where === 'device' ? 'This browser' : 'Server, encrypted'} · ••••{k.last4}</span>
                <button type="button" className="icon-btn icon-btn-sm" aria-label={`Remove the ${label(k.name)} key`}
                  onClick={() => (k.where === 'device' ? removeDevice(k.name) : void removeServer(k.name))}>
                  <Trash2 size={14} strokeWidth={1.75} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Dialog>
  );
}
