import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Check, X } from 'lucide-react';
import styles from './ui.module.css';

type Tone = 'neutral' | 'good' | 'bad';
interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const push = useCallback(
    (message: string, tone: Tone = 'neutral') => {
      const id = nextId.current++;
      setToasts((t) => [...t.slice(-2), { id, message, tone }]);
      window.setTimeout(() => dismiss(id), tone === 'bad' ? 7000 : 4000);
    },
    [dismiss],
  );

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.toastRegion} role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={styles.toast} data-tone={t.tone}>
            {t.tone === 'good' && <Check size={15} strokeWidth={2} />}
            {t.tone === 'bad' && <AlertCircle size={15} strokeWidth={1.75} />}
            <span>{t.message}</span>
            <button type="button" className="icon-btn icon-btn-sm" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              <X size={14} strokeWidth={1.75} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
