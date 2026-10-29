import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AccountInfo } from '../api';
import { Dialog } from './ui/Dialog';

interface AccountDialogProps {
  open: boolean;
  onClose: () => void;
  onSignOut: () => void;
  onDeleted: () => void;
}

const PROVIDERS: Record<string, string> = { email: 'E-mailed code', google: 'Google', github: 'GitHub', local: 'Local profile' };

function Meter({ label, used, limit, unit = '' }: { label: string; used: number; limit: number; unit?: string }) {
  const share = Math.min(1, limit ? used / limit : 0);
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-sm)' }}>
        <span>{label}</span>
        <span style={{ color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>
          {used.toLocaleString()}{unit} of {limit.toLocaleString()}{unit}
        </span>
      </div>
      <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used}
        style={{ marginTop: 6, height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
        <div style={{ width: `${share * 100}%`, height: '100%', background: share > 0.9 ? 'var(--bad)' : 'var(--accent)' }} />
      </div>
    </div>
  );
}

/** The signed-in account: how it signs in, today's usage against the server's limits, and deleting it. */
export function AccountDialog({ open, onClose, onSignOut, onDeleted }: AccountDialogProps) {
  const [info, setInfo] = useState<AccountInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);

  // The dialog is remounted each time it opens (see App), so its state starts fresh.
  useEffect(() => {
    if (!open) return;
    api.getAccount().then(setInfo).catch((e: Error) => setError(e.message));
  }, [open]);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount();
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const mb = (bytes: number) => Math.round((bytes / (1024 * 1024)) * 10) / 10;

  return (
    <Dialog open={open} onClose={onClose} title="Account" description={info ? info.user.email : undefined}>
      {info && (
        <>
          <p style={{ color: 'var(--text-2)', fontSize: 'var(--text-sm)' }}>
            Signs in with {PROVIDERS[info.user.provider] || info.user.provider}
            {info.admin ? ' · administrator' : ''}
          </p>
          {info.limits ? (
            <>
              <Meter label="Questions today" used={info.usage.questions} limit={info.limits.questions_per_day} />
              <Meter label="Uploads today" used={info.usage.uploads} limit={info.limits.uploads_per_day} />
              <Meter label="Library storage" used={mb(info.storage_bytes)} limit={info.limits.storage_mb} unit=" MB" />
              <p style={{ marginTop: 12, color: 'var(--text-3)', fontSize: 'var(--text-xs)' }}>Daily limits reset at midnight UTC.</p>
            </>
          ) : (
            <p style={{ marginTop: 12, color: 'var(--text-2)', fontSize: 'var(--text-sm)' }}>
              {mb(info.storage_bytes)} MB in your library. No limits apply to this account.
            </p>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 24 }}>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)} disabled={confirming}>
              Delete account…
            </button>
            <button type="button" className="btn btn-secondary" onClick={onSignOut}>
              Sign out
            </button>
          </div>
          {confirming && (
            <div style={{ marginTop: 16, padding: 14, borderRadius: 'var(--radius-md)', background: 'var(--bad-soft)' }}>
              <p style={{ fontSize: 'var(--text-sm)' }}>
                This permanently deletes your documents, their indexes and your conversations. Type <strong>delete</strong> to confirm.
              </p>
              <input className="field" style={{ marginTop: 10 }} value={typed} onChange={(e) => setTyped(e.target.value)}
                aria-label="Type delete to confirm" autoComplete="off" />
              <button type="button" className="btn btn-danger" style={{ marginTop: 10 }} disabled={typed.trim().toLowerCase() !== 'delete' || busy}
                onClick={remove}>
                {busy && <span className="spinner" />} Delete my account and data
              </button>
            </div>
          )}
        </>
      )}
      {error && (
        <p role="alert" style={{ marginTop: 12, color: 'var(--bad)', fontSize: 'var(--text-sm)' }}>
          {error}
        </p>
      )}
    </Dialog>
  );
}
