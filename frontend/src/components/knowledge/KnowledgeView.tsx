import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type JSX } from 'react';
import {
  Globe2,
  Library,
  List,
  Minus,
  PanelLeftOpen,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';
import { api } from '../../api';
import type { GraphData } from '../../api';
import { useTheme } from '../../lib/theme';
import { computeGlobeLayout } from './globeLayout';
import { GlobeScene } from './GlobeScene';
import type { GlobeSceneClassNames } from './GlobeScene';
import { buildGraphModel, familyCounts, findEntitiesByName, plural, searchEntities } from './graphModel';
import type { GraphModel } from './graphModel';
import { DetailPanel } from './DetailPanel';
import { EntityList } from './EntityList';
import { Legend } from './Legend';
import { isTypingTarget, useReducedMotion } from './ui';
import styles from './KnowledgeView.module.css';

export interface KnowledgeViewProps {
  onAskAboutEntity: (entityName: string) => void;
  onOpenLibrary?: () => void;
  /** Entities to highlight on load (case-insensitive names); the first one gets focus. */
  focusEntityNames?: string[];
  initialData?: GraphData;
  /** When the app sidebar is closed, the header shows a button to reopen it. */
  sidebarOpen?: boolean;
  onOpenSidebar?: () => void;
}

type LoadState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: GraphData };

const GRAPH_LIMIT = 2000;
const LAYOUT_SEED = 7;
const ICON = { size: 16, strokeWidth: 1.75, 'aria-hidden': true } as const;
const NARROW_QUERY = '(max-width: 720px)';
const NO_NAMES: string[] = [];

const SCENE_CLASSES: GlobeSceneClassNames = {
  canvas: styles.canvas,
  overlay: styles.overlay,
  label: styles.label,
  labelActive: styles.labelActive,
  labelStrong: styles.labelStrong,
  ring: styles.ring,
  tooltip: styles.tooltip,
  tooltipName: styles.tooltipName,
  tooltipMeta: styles.tooltipMeta,
  tooltipDot: styles.tooltipDot,
};

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(NARROW_QUERY);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return narrow;
}

function SidebarButton({ show, onOpen }: { show: boolean; onOpen?: () => void }) {
  if (!show || !onOpen) return null;
  return (
    <button type="button" className={`icon-btn ${styles.sidebarBtn}`} onClick={onOpen} aria-label="Open sidebar" title="Open sidebar">
      <PanelLeftOpen size={18} strokeWidth={1.75} />
    </button>
  );
}

/** The knowledge graph as an interactive 3D globe, with search, filters, details and a list twin. */
export function KnowledgeView(props: KnowledgeViewProps): JSX.Element {
  const { initialData, onOpenLibrary, sidebarOpen = true, onOpenSidebar } = props;
  const [fetched, setFetched] = useState<LoadState>({ status: 'loading' });
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    api
      .getGraph(GRAPH_LIMIT)
      .then((data) => {
        if (!cancelled) setFetched({ status: 'ready', data });
      })
      .catch((e: unknown) => {
        if (!cancelled) setFetched({ status: 'error', message: e instanceof Error ? e.message : 'Could not load the knowledge graph' });
      });
    return () => {
      cancelled = true;
    };
  }, [initialData, reloadKey]);

  const reload = () => {
    setFetched({ status: 'loading' });
    setReloadKey((k) => k + 1);
  };

  const load: LoadState = initialData ? { status: 'ready', data: initialData } : fetched;
  const data = load.status === 'ready' ? load.data : null;
  const model = useMemo(() => buildGraphModel(data), [data]);
  const sidebarButton = <SidebarButton show={!sidebarOpen} onOpen={onOpenSidebar} />;

  if (load.status === 'loading') {
    return (
      <div className={styles.root}>
        {sidebarButton}
        <div className={styles.state} role="status">
          <div className={styles.loadingGlobe} aria-hidden="true" />
          <p className={styles.stateText}>Loading the knowledge graph…</p>
        </div>
      </div>
    );
  }

  if (load.status === 'error') {
    return (
      <div className={styles.root}>
        {sidebarButton}
        <div className={styles.state} role="alert">
          <p className={styles.stateTitle}>The knowledge graph didn’t load</p>
          <p className={styles.stateText}>{load.message}</p>
          <button type="button" className="btn btn-secondary btn-sm" onClick={reload}>
            <RefreshCw {...ICON} size={14} /> Try again
          </button>
        </div>
      </div>
    );
  }

  if (!model.entities.length) {
    return (
      <div className={styles.root}>
        {sidebarButton}
        <div className={styles.state}>
          <Globe2 size={28} strokeWidth={1.5} className={styles.stateIcon} aria-hidden="true" />
          <p className={styles.stateTitle}>No knowledge graph yet</p>
          <p className={styles.stateText}>
            Entities and relations appear here as your documents are read. Large documents can take a few minutes.
          </p>
          <div className={styles.stateActions}>
            {onOpenLibrary && (
              <button type="button" className="btn btn-primary btn-sm" onClick={onOpenLibrary}>
                <Library {...ICON} size={14} /> Open library
              </button>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={reload}>
              <RefreshCw {...ICON} size={14} /> Refresh
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Remounting per dataset resets every filter and selection with it.
  return <GlobeExplorer key={reloadKey} {...props} model={model} sidebarButton={sidebarButton} />;
}

interface GlobeExplorerProps extends KnowledgeViewProps {
  model: GraphModel;
  sidebarButton: JSX.Element;
}

function GlobeExplorer({ model, onAskAboutEntity, focusEntityNames = NO_NAMES, sidebarButton }: GlobeExplorerProps): JSX.Element {
  const layout = useMemo(() => computeGlobeLayout(model.entities.length, model.pairs, { seed: LAYOUT_SEED }), [model]);
  const [initialFocus] = useState(() => findEntitiesByName(model, focusEntityNames));

  const [docFilter, setDocFilter] = useState('all');
  const [hiddenFamilies, setHiddenFamilies] = useState<Set<string>>(() => new Set());
  const [isolate, setIsolate] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<number | null>(initialFocus[0] ?? null);
  const [focusSet, setFocusSet] = useState<number[]>(initialFocus);
  const [showList, setShowList] = useState(false);
  const [rotating, setRotating] = useState(true);
  const [legendOpen, setLegendOpen] = useState(false);
  const [webglFailed, setWebglFailed] = useState(false);
  const [scene, setScene] = useState<GlobeScene | null>(null);

  const reduced = useReducedMotion();
  const narrow = useNarrow();
  const { resolved: theme } = useTheme();

  const rootRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const inDoc = useCallback((docId: string | null) => docFilter === 'all' || docId === docFilter, [docFilter]);

  const visible = useMemo(() => {
    const mask = new Uint8Array(model.entities.length);
    for (const e of model.entities) mask[e.index] = inDoc(e.docId) && !hiddenFamilies.has(e.family.key) ? 1 : 0;
    return mask;
  }, [model, inDoc, hiddenFamilies]);

  // A selection hidden by a filter stops being shown.
  const current = selected !== null && visible[selected] ? selected : null;
  const visibleCount = useMemo(() => visible.reduce((a, v) => a + v, 0), [visible]);
  const visibleRelations = useMemo(
    () => model.relations.reduce((a, r) => a + (visible[r.source] && visible[r.target] ? 1 : 0), 0),
    [model, visible],
  );
  const legendItems = useMemo(() => familyCounts(model, (e) => inDoc(e.docId)), [model, inDoc]);
  const matches = useMemo(() => (query.trim() ? searchEntities(model, query, visible) : []), [model, query, visible]);
  const highlight = useMemo(() => {
    const list = query.trim() ? matches : focusSet;
    return list.length ? new Set(list) : null;
  }, [query, matches, focusSet]);

  // ---- scene lifecycle (WebGL is an external system; React only feeds it state)
  const onSceneSelect = useRef<(index: number | null) => void>(() => undefined);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let created: GlobeScene;
    try {
      created = new GlobeScene({
        host,
        classNames: SCENE_CLASSES,
        reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
        onSelect: (i) => onSceneSelect.current(i),
      });
    } catch {
      setWebglFailed(true);
      setShowList(true);
      return;
    }
    setScene(created);
    return () => {
      created.dispose();
      setScene(null);
    };
  }, []);

  const select = useCallback(
    (index: number | null) => {
      setSelected(index);
      if (index !== null) scene?.flyTo(index);
    },
    [scene],
  );

  useEffect(() => {
    onSceneSelect.current = select;
  }, [select]);

  useEffect(() => {
    if (!scene) return;
    scene.setGraph(model, layout.positions, layout.spacing);
    if (initialFocus.length) scene.flyTo(initialFocus[0]);
  }, [scene, model, layout, initialFocus]);

  useEffect(() => {
    scene?.setVisible(visible);
  }, [scene, visible, layout]);

  useEffect(() => {
    scene?.setFocus({ selected: current, matches: highlight, isolateFamily: isolate });
  }, [scene, current, highlight, isolate, layout]);

  useEffect(() => {
    scene?.setDescription(
      `Knowledge globe: ${plural(visibleCount, 'entity', 'entities')} and ${plural(visibleRelations, 'relation', 'relations')}. ` +
        'Use the list view for a text alternative.',
    );
  }, [scene, visibleCount, visibleRelations]);

  useEffect(() => {
    scene?.setTheme();
  }, [scene, theme]);

  useEffect(() => {
    scene?.setReducedMotion(reduced);
  }, [scene, reduced]);

  useEffect(() => {
    scene?.setAutoRotate(rotating && !reduced);
  }, [scene, rotating, reduced]);

  // The globe centres in the space the chrome leaves free.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || !scene) return;
    const measure = () => {
      const r = root.getBoundingClientRect();
      const insets = { top: 0, right: 0, bottom: 0, left: 0 };
      const head = headRef.current?.getBoundingClientRect();
      if (head) insets.top = Math.max(0, head.bottom - r.top);
      const det = detailRef.current?.getBoundingClientRect();
      if (det) {
        if (det.width > r.width * 0.7) insets.bottom = Math.max(0, r.bottom - det.top);
        else insets.right = Math.max(0, r.right - det.left);
      }
      const list = listRef.current?.getBoundingClientRect();
      if (list && list.width < r.width * 0.7) insets.left = Math.max(0, list.right - r.left);
      scene.setInsets(insets);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    if (headRef.current) ro.observe(headRef.current);
    if (detailRef.current) ro.observe(detailRef.current);
    if (listRef.current) ro.observe(listRef.current);
    return () => ro.disconnect();
  }, [scene, current, showList]);

  // ---- keyboard: "/" focuses search, Esc steps back one level
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '/' && !isTypingTarget(e.target)) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (e.key === 'Escape') {
        if (current !== null) setSelected(null);
        else if (query) setQuery('');
        else if (focusSet.length) setFocusSet([]);
        else return;
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [current, query, focusSet]);

  const toggleFamily = (key: string) =>
    setHiddenFamilies((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const listRows = useMemo(
    () => (query.trim() ? matches : model.byDegree.filter((i) => visible[i])),
    [query, matches, model, visible],
  );

  const docCount = model.documents.length;
  const focusNote = !query.trim() && focusSet.length > 0 ? `${plural(focusSet.length, 'entity', 'entities')} from your answer` : null;
  const sheetOpen = narrow && current !== null;

  return (
    <div className={styles.root} ref={rootRef} data-list={showList || undefined}>
      <div ref={hostRef} className={styles.stage} hidden={webglFailed} />

      <header ref={headRef} className={styles.head}>
        <div className={styles.titleBlock}>
          {sidebarButton}
          <div>
            <h1 className={styles.title}>Knowledge</h1>
            <p className={styles.counts}>
              {plural(visibleCount, 'entity', 'entities')} · {plural(visibleRelations, 'relation', 'relations')}
              {docCount > 0 && <> · {plural(docCount, 'document', 'documents')}</>}
            </p>
          </div>
        </div>

        <div className={styles.toolbar}>
          <label className={styles.search}>
            <Search {...ICON} size={15} className={styles.searchIcon} />
            <span className="visually-hidden">Search entities</span>
            <input
              ref={searchRef}
              type="search"
              className={styles.searchInput}
              placeholder="Search entities"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && matches.length) {
                  e.preventDefault();
                  select(matches[0]);
                } else if (e.key === 'Escape' && query) {
                  e.preventDefault();
                  setQuery('');
                }
              }}
              aria-describedby={query.trim() ? 'kv-search-count' : undefined}
            />
            {query ? (
              <button type="button" className={styles.searchClear} onClick={() => setQuery('')} aria-label="Clear search">
                <X {...ICON} size={14} />
              </button>
            ) : (
              <kbd className="kbd" aria-hidden="true">
                /
              </kbd>
            )}
          </label>
          {query.trim() && (
            <span id="kv-search-count" className={styles.searchCount} aria-live="polite">
              {matches.length ? plural(matches.length, 'match', 'matches') : 'No matches'}
            </span>
          )}

          {docCount > 1 && (
            <label className={styles.selectWrap}>
              <span className="visually-hidden">Document</span>
              <select className={styles.select} value={docFilter} onChange={(e) => setDocFilter(e.target.value)}>
                <option value="all">All documents</option>
                {model.documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
              </select>
            </label>
          )}

          <button
            type="button"
            className={styles.toggleBtn}
            aria-pressed={showList}
            onClick={() => setShowList((v) => !v)}
            disabled={webglFailed}
            title={showList ? 'Hide the entity list' : 'Show every entity as a list'}
          >
            <List {...ICON} size={15} /> List
          </button>
        </div>

        {focusNote && (
          <p className={styles.focusNote}>
            <span>{focusNote}</span>
            <button type="button" className={styles.textBtn} onClick={() => setFocusSet([])}>
              Clear
            </button>
          </p>
        )}
      </header>

      {webglFailed && (
        <p className={styles.notice} role="note">
          The 3D globe needs WebGL, which this browser has turned off. The list shows the same entities.
        </p>
      )}

      {showList && (
        <div ref={listRef} className={styles.listSlot}>
          <EntityList
            model={model}
            rows={listRows}
            selected={current}
            onSelect={select}
            note={`${plural(listRows.length, 'entity', 'entities')}${query.trim() ? ` matching “${query.trim()}”` : ', most connected first'}`}
          />
        </div>
      )}

      {!webglFailed && (
        <>
          <div className={styles.legendSlot} data-hidden={sheetOpen || undefined}>
            <Legend
              items={legendItems}
              hidden={hiddenFamilies}
              onToggle={toggleFamily}
              onShowAll={() => setHiddenFamilies(new Set())}
              onIsolate={setIsolate}
              collapsible={narrow}
              open={legendOpen}
              onOpenChange={setLegendOpen}
            />
          </div>

          <div className={styles.controls} role="toolbar" aria-label="Globe controls" data-hidden={sheetOpen || undefined}>
            <button type="button" className={styles.ctrlBtn} onClick={() => scene?.zoomBy(0.8)} aria-label="Zoom in" title="Zoom in">
              <Plus {...ICON} />
            </button>
            <button type="button" className={styles.ctrlBtn} onClick={() => scene?.zoomBy(1.25)} aria-label="Zoom out" title="Zoom out">
              <Minus {...ICON} />
            </button>
            <button
              type="button"
              className={styles.ctrlBtn}
              onClick={() => scene?.resetView()}
              aria-label="Reset view"
              title="Reset view (or double-click empty space)"
            >
              <RotateCcw {...ICON} />
            </button>
            {!reduced && (
              <button
                type="button"
                className={styles.ctrlBtn}
                onClick={() => setRotating((r) => !r)}
                aria-pressed={!rotating}
                aria-label={rotating ? 'Pause rotation' : 'Resume rotation'}
                title={rotating ? 'Pause rotation' : 'Resume rotation'}
              >
                {rotating ? <Pause {...ICON} /> : <Play {...ICON} />}
              </button>
            )}
          </div>
        </>
      )}

      {current !== null && (
        <DetailPanel
          key={current}
          model={model}
          index={current}
          panelRef={detailRef}
          onClose={() => setSelected(null)}
          onNavigate={select}
          onAsk={onAskAboutEntity}
        />
      )}
    </div>
  );
}
