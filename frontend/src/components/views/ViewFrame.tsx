import type { ReactNode } from 'react';
import { PanelLeftOpen } from 'lucide-react';
import styles from './views.module.css';

interface ViewFrameProps {
  title: string;
  description?: ReactNode;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
  /** Buttons beside the title. */
  actions?: ReactNode;
  children: ReactNode;
  /** A side panel, usually the document viewer. */
  panel?: ReactNode;
  wide?: boolean;
}

/** The page every library tool shares: a title, its explanation, the content, and room for the viewer. */
export function ViewFrame({ title, description, sidebarOpen, onOpenSidebar, actions, children, panel, wide = false }: ViewFrameProps) {
  return (
    <div className={styles.layout}>
      <div className={styles.page}>
        <header className={styles.topbar}>
          {!sidebarOpen && (
            <button type="button" className="icon-btn" onClick={onOpenSidebar} aria-label="Open sidebar">
              <PanelLeftOpen size={18} strokeWidth={1.75} />
            </button>
          )}
        </header>
        <main className={styles.content} data-wide={wide || undefined} id="main">
          <div className={styles.titleRow}>
            <div>
              <h1 className={styles.title}>{title}</h1>
              {description && <p className={styles.subtitle}>{description}</p>}
            </div>
            {actions && <div className={styles.actions}>{actions}</div>}
          </div>
          {children}
        </main>
      </div>
      {panel}
    </div>
  );
}

/** A message in place of content: nothing yet, nothing found, or something went wrong. */
export function EmptyState({ title, text, action }: { title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <strong>{title}</strong>
      {text && <p>{text}</p>}
      {action}
    </div>
  );
}
