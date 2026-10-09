import { useEffect, useState } from 'react';
import { Check, CircleDashed, Copy, ExternalLink } from 'lucide-react';
import { api } from '../api';
import type { ProvidersInfo } from '../api';
import { Dialog } from './ui/Dialog';
import styles from './ProvidersDialog.module.css';

/** Which free hosted model, search and embedding providers are set up, and how to add one. */
export function ProvidersDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<ProvidersInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api
      .getProviders()
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, [open]);

  const copy = (text: string) =>
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(text);
      window.setTimeout(() => setCopied(null), 1400);
    });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={620}
      title="Models and search"
      description="Hosted free tiers answer much faster than local models and spare your computer. Add a key to the .env file next to server.py and restart the server; the first configured provider answers and the others take over when it is rate-limited."
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          Done
        </button>
      }
    >
      {error && <p role="alert">{error}</p>}
      {!info && !error && <span className="spinner" />}
      {info && (
        <div className={styles.body}>
          <p className={styles.current}>
            Answers use <strong>{info.current_model}</strong> · embeddings {info.embedding_model || 'not loaded'} · Ollama{' '}
            {info.ollama ? 'running' : 'not running'}
          </p>
          <h3 className={styles.heading}>Language models</h3>
          <ul className={styles.list}>
            {info.llm.filter((p) => p.name !== 'jina').map((p) => (
              <li key={p.name} data-on={p.configured}>
                {p.configured ? <Check size={15} strokeWidth={2.2} /> : <CircleDashed size={15} strokeWidth={1.75} />}
                <div className={styles.provider}>
                  <div className={styles.row}>
                    <strong>{p.label}</strong>
                    {p.model && <span className={styles.model}>{p.model}</span>}
                    {p.cooling_down_s > 0 && <span className={styles.cool}>rate-limited, back in {p.cooling_down_s}s</span>}
                  </div>
                  <span className={styles.note}>{p.free_note}</span>
                  {!p.configured && p.key_env && (
                    <span className={styles.row}>
                      <button type="button" className={styles.env} onClick={() => copy(`${p.key_env}=`)} title="Copy for .env">
                        {copied === `${p.key_env}=` ? <Check size={12} strokeWidth={2.4} /> : <Copy size={12} strokeWidth={2} />} {p.key_env}=
                      </button>
                      {p.sign_up && (
                        <a href={p.sign_up} target="_blank" rel="noreferrer noopener">
                          Get a key <ExternalLink size={12} strokeWidth={2} />
                        </a>
                      )}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <h3 className={styles.heading}>Web search</h3>
          <ul className={styles.list}>
            {info.search.map((p) => (
              <li key={p.name} data-on={p.configured}>
                {p.configured ? <Check size={15} strokeWidth={2.2} /> : <CircleDashed size={15} strokeWidth={1.75} />}
                <div className={styles.provider}>
                  <div className={styles.row}>
                    <strong>{p.label}</strong>
                    {!p.key_env && <span className={styles.note}>no key needed (fallback)</span>}
                  </div>
                  {!p.configured && p.key_env && (
                    <button type="button" className={styles.env} onClick={() => copy(`${p.key_env}=`)}>
                      {copied === `${p.key_env}=` ? <Check size={12} strokeWidth={2.4} /> : <Copy size={12} strokeWidth={2} />} {p.key_env}=
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}
