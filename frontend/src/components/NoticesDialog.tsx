import { useEffect, useState } from 'react';
import { Megaphone, ShieldAlert } from 'lucide-react';
import { api } from '../api';
import type { Notice } from '../api';
import { Dialog } from './ui/Dialog';
import styles from './NoticesDialog.module.css';

interface NoticesDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called once the notices are marked read, so the unread dot can clear. */
  onRead: () => void;
}

function when(seconds: number): string {
  const d = new Date(seconds * 1000);
  const days = (Date.now() - d.getTime()) / 86_400_000;
  if (days < 1) return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: days > 300 ? 'numeric' : undefined });
}

/** Security events on this account (new sign-ins, passkeys, codes) and announcements such as What's new. */
export function NoticesDialog({ open, onClose, onRead }: NoticesDialogProps) {
  const [notices, setNotices] = useState<Notice[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Remounted each time it opens (see App): show what was unread, then mark it read.
  useEffect(() => {
    if (!open) return;
    api.listNotices()
      .then(async (data) => {
        setNotices(data.notices);
        if (data.unread) {
          await api.readNotices();
          onRead();
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [open, onRead]);

  return (
    <Dialog open={open} onClose={onClose} title="Notifications" description="Sign-in activity on your account and news about OmniDoc." width={520}>
      {notices && !notices.length && <p className={styles.empty}>Nothing yet. New sign-ins and updates will show up here.</p>}
      {notices && notices.length > 0 && (
        <ol className={styles.list}>
          {notices.map((n) => {
            const Icon = n.kind === 'security' ? ShieldAlert : Megaphone;
            return (
              <li key={n.id} data-unread={!n.read || undefined}>
                <Icon size={16} strokeWidth={1.75} className={styles.icon} data-kind={n.kind} />
                <div className={styles.text}>
                  <div className={styles.head}>
                    <span className={styles.title}>{n.title}</span>
                    <time className={styles.time} dateTime={new Date(n.created_at * 1000).toISOString()}>{when(n.created_at)}</time>
                  </div>
                  {n.body && <p className={styles.body}>{n.body}</p>}
                  {n.url && (
                    <a className={styles.more} href={n.url} target="_blank" rel="noreferrer">Read the release notes</a>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </Dialog>
  );
}
