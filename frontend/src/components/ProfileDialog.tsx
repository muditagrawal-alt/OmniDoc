import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import type { User } from '../api';
import { Dialog } from './ui/Dialog';

interface ProfileDialogProps {
  open: boolean;
  onClose: () => void;
  onSignedIn: (user: User) => void;
}

/**
 * OmniDoc runs on your machine, so there is no cloud account: a profile is a
 * local name + email that keeps one person's conversations separate.
 */
export function ProfileDialog({ open, onClose, onSignedIn }: ProfileDialogProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError('Enter a valid email address.');
      return;
    }
    setBusy(true);
    try {
      const user = await api.login(name.trim(), email.trim());
      onSignedIn(user);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Create a local profile"
      description="Profiles stay on this machine and keep conversations separate when several people share it. There is no password and nothing leaves your computer."
    >
      <form onSubmit={submit} noValidate>
        <label className="field-label" htmlFor="profile-name">
          Name
        </label>
        <input id="profile-name" className="field" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        <label className="field-label" htmlFor="profile-email" style={{ marginTop: 14 }}>
          Email
        </label>
        <input
          id="profile-email"
          className="field"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          aria-invalid={!!error}
          aria-describedby={error ? 'profile-error' : undefined}
        />
        {error && (
          <p id="profile-error" role="alert" style={{ marginTop: 8, color: 'var(--bad)', fontSize: 'var(--text-sm)' }}>
            {error}
          </p>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 22 }}>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy && <span className="spinner" />} Continue
          </button>
        </div>
      </form>
    </Dialog>
  );
}
