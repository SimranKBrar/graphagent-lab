import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import dagre from '@dagrejs/dagre';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react';
import { api, ApiError } from '../api/client';
import type {
  GraphData,
  GraphNode,
  GraphNodeDetail,
  GraphStatusResponse,
  RepoSummary,
  RunEvent,
  RunSummary,
  SystemID,
} from '../api/types';
import {
  EmptyState,
  ErrorBanner,
  Spinner,
  SYSTEM_META,
} from '../components/ui';

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

// ---------------------------------------------------------------------------
// Node / edge model
// ---------------------------------------------------------------------------

const NODE_W = 176;
const NODE_H = 56;

interface GNodeData extends Record<string, unknown> {
  label: string;
  kind: string;
  file?: string | null;
  line?: number | null;
  gnn?: number | null;
  gnnImpact?: number | null;
  visited?: boolean;
  accent?: string;
  trail?: number | null;
  edited?: boolean;
}

type GFlowNode = Node<GNodeData, 'gnode'>;
type GFlowEdge = Edge;

const EDGE_COLORS: Record<string, string> = {
  calls: '#60a5fa',
  imports: '#34d399',
  inherits: '#a78bfa',
  defines: '#94a3b8',
  tests: '#f59e0b',
};

const EDGE_TYPES = ['calls', 'imports', 'inherits', 'defines', 'tests'];

const KIND_COLORS: Record<string, string> = {
  module: '#38bdf8',
  function: '#60a5fa',
  class: '#a78bfa',
  test_function: '#34d399',
};

function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? '#9ca3af';
}

function GNode({ data, selected }: NodeProps<GFlowNode>) {
  const style = {
    '--accent': data.accent ?? '#60a5fa',
    borderColor: selected ? '#e5e7eb' : undefined,
  } as CSSProperties;
  return (
    <div
      className={[
        'gnode',
        `gn-${data.kind}`,
        data.visited ? 'visited' : '',
        data.edited ? 'edited' : '',
        data.gnn != null ? 'gnn-predicted' : '',
        selected ? 'is-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
    >
      <Handle type="target" position={Position.Left} />
      <div className="gnode-label" title={`${data.file ?? ''}${data.line != null ? `:${data.line}` : ''}`}>
        {data.label}
      </div>
      <div className="gnode-meta">
        <span className="gnode-kind">{data.kind}</span>
        {data.gnn != null && (
          <span className="gnn-badge" title="GNN impact score (dashed = predicted)">
            GNN {data.gnn.toFixed(2)}
          </span>
        )}
        {data.edited && <span className="edited-badge">edited</span>}
        {data.trail != null && <span className="trail-badge">{data.trail}</span>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES: NodeTypes = { gnode: GNode };

/** Client-side dagre layout (the API sends node-link data without positions). */
function layoutGraph(nodes: GFlowNode[], edges: { source: string; target: string }[]): GFlowNode[] {
  if (nodes.length === 0) return [];
  try {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 26, ranksep: 76, marginx: 24, marginy: 24 });
    g.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
    edges.forEach((e) => {
      if (e.source !== e.target) g.setEdge(e.source, e.target);
    });
    dagre.layout(g);
    return nodes.map((n) => {
      const p = g.node(n.id) as { x: number; y: number } | undefined;
      if (!p) return n;
      return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
    });
  } catch {
    return nodes; // dagre failure — fall back to the origin grid
  }
}

// ---------------------------------------------------------------------------
// Run overlay state derived from the event log
// ---------------------------------------------------------------------------

interface OverlayInfo {
  visitedBy: Map<string, SystemID>;
  trailNo: Map<string, number>;
  order: string[];
  editedFiles: Set<string>;
}

// ---------------------------------------------------------------------------
// Explorer (must live inside ReactFlowProvider for setCenter)
// ---------------------------------------------------------------------------

function Explorer() {
  // Repos -------------------------------------------------------------------
  const [repos, setRepos] = useState<RepoSummary[] | null>(null);
  const [reposErr, setReposErr] = useState<string | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);

  // Graph data --------------------------------------------------------------
  const [data, setData] = useState<GraphData | null>(null);
  const [dataErr, setDataErr] = useState<string | null>(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataTick, setDataTick] = useState(0);
  const [gstatus, setGStatus] = useState<GraphStatusResponse | null>(null);

  // Filters -----------------------------------------------------------------
  const [disabledKinds, setDisabledKinds] = useState<Set<string>>(new Set());

  // Search ------------------------------------------------------------------
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GraphNode[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);

  // Node detail -------------------------------------------------------------
  const [detail, setDetail] = useState<GraphNodeDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Run overlay -------------------------------------------------------------
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [overlayRunId, setOverlayRunId] = useState('');
  const [overlaySys, setOverlaySys] = useState<SystemID | 'all'>('all');
  const [overlayEvents, setOverlayEvents] = useState<RunEvent[] | null>(null);
  const [overlayLoading, setOverlayLoading] = useState(false);
  const [overlayErr, setOverlayErr] = useState<string | null>(null);
  const [showTrail, setShowTrail] = useState(true);
  const [scrub, setScrub] = useState(0);
  const [scrubMax, setScrubMax] = useState(0);

  const posRef = useRef<Record<string, { x: number; y: number }>>({});
  const rf = useReactFlow();

  // ------------------------------------------------------------------ loads
  useEffect(() => {
    api
      .listRepos()
      .then((r) => {
        setRepos(r);
        if (r.length > 0)
          setRepoId((prev) => prev ?? (r.find((x) => x.graph_status === 'ready') ?? r[0]).id);
      })
      .catch((e) => setReposErr(errMsg(e)));
  }, []);

  useEffect(() => {
    api
      .listRuns()
      .then(setRuns)
      .catch(() => setRuns([]));
  }, []);

  useEffect(() => {
    setData(null);
    setDataErr(null);
    setGStatus(null);
    setDetail(null);
    setDetailErr(null);
    setResults(null);
    setDisabledKinds(new Set());
    setOverlayRunId('');
    setOverlayEvents(null);
    if (!repoId) return;
    let cancelled = false;
    setDataLoading(true);
    (async () => {
      try {
        const [gd, gs] = await Promise.all([
          api.getGraphData(repoId),
          api.getGraph(repoId),
        ]);
        if (cancelled) return;
        setData(gd);
        setGStatus(gs);
      } catch (e) {
        if (!cancelled) setDataErr(errMsg(e));
      } finally {
        if (!cancelled) setDataLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [repoId, dataTick]);

  // Overlay events (GET /api/runs/{id}/events?format=json) ------------------
  useEffect(() => {
    if (!overlayRunId) {
      setOverlayEvents(null);
      setScrub(0);
      setScrubMax(0);
      return;
    }
    let cancelled = false;
    setOverlayLoading(true);
    setOverlayErr(null);
    api
      .getRunEvents(overlayRunId, 0)
      .then((res) => {
        if (cancelled) return;
        const evs = (res.events ?? []).slice().sort((a, b) => a.seq - b.seq);
        setOverlayEvents(evs);
        const max = evs.length ? evs[evs.length - 1].seq : 0;
        setScrubMax(max);
        setScrub(max);
      })
      .catch((e) => {
        if (!cancelled) setOverlayErr(errMsg(e));
      })
      .finally(() => {
        if (!cancelled) setOverlayLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [overlayRunId]);

  // --------------------------------------------------------------- overlay
  const overlay = useMemo<OverlayInfo>(() => {
    const res: OverlayInfo = {
      visitedBy: new Map(),
      trailNo: new Map(),
      order: [],
      editedFiles: new Set(),
    };
    if (!overlayEvents || overlayEvents.length === 0) return res;
    let n = 0;
    for (const ev of overlayEvents) {
      if (ev.seq > scrub) break;
      if (overlaySys !== 'all' && ev.system !== overlaySys) continue;
      if (ev.type === 'graph_visit') {
        const ids: unknown[] = Array.isArray(ev.payload?.node_ids) ? ev.payload.node_ids : [];
        for (const raw of ids) {
          const id = String(raw);
          if (res.visitedBy.has(id)) continue;
          res.visitedBy.set(id, ev.system ?? 'A');
          res.trailNo.set(id, ++n);
          res.order.push(id);
        }
      } else if (ev.type === 'edit_applied') {
        const path: unknown = ev.payload?.path;
        if (typeof path === 'string' && path) res.editedFiles.add(path);
      }
    }
    return res;
  }, [overlayEvents, overlaySys, scrub]);

  // --------------------------------------------------------------- layout
  const baseNodes = useMemo<GFlowNode[]>(() => {
    if (!data) return [];
    const skeleton: GFlowNode[] = (data.nodes ?? []).map((n) => ({
      id: n.id,
      type: 'gnode',
      position: { x: 0, y: 0 },
      draggable: false,
      data: {
        label: n.label ?? n.id,
        kind: n.kind ?? 'function',
        file: n.file,
        line: n.line,
        gnn: n.gnn_score,
        gnnImpact: n.gnn_impact,
      },
    }));
    const laid = layoutGraph(skeleton, data.edges ?? []);
    const pos: Record<string, { x: number; y: number }> = {};
    for (const n of laid) {
      pos[n.id] = { x: n.position.x + NODE_W / 2, y: n.position.y + NODE_H / 2 };
    }
    posRef.current = pos;
    return laid;
  }, [data]);

  const rfNodes = useMemo<GFlowNode[]>(() => {
    return baseNodes.map((n) => {
      const d = n.data;
      const visitSys = overlay.visitedBy.get(n.id);
      const edited = !!(d.file && overlay.editedFiles.has(d.file));
      return {
        ...n,
        hidden: disabledKinds.has(d.kind),
        data: {
          ...d,
          visited: visitSys !== undefined,
          accent: visitSys !== undefined ? SYSTEM_META[visitSys].color : undefined,
          trail: showTrail ? overlay.trailNo.get(n.id) ?? null : null,
          edited,
        },
      };
    });
  }, [baseNodes, overlay, disabledKinds, showTrail]);

  const rfEdges = useMemo<GFlowEdge[]>(() => {
    if (!data) return [];
    const byId = new Map(rfNodes.map((n) => [n.id, n]));
    const edges: GFlowEdge[] = [];
    const overlayActive = overlay.visitedBy.size > 0 || overlay.editedFiles.size > 0;

    for (const e of data.edges ?? []) {
      const s = byId.get(e.source);
      const t = byId.get(e.target);
      if (!s || !t) continue; // defensive: drop dangling edges
      const col = EDGE_COLORS[e.type] ?? '#475569';
      edges.push({
        id: e.id || `e:${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        type: 'smoothstep',
        className: `ge edge-${e.type}`,
        style: { stroke: col, strokeWidth: 1.5, opacity: overlayActive ? 0.3 : 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 11, height: 11 },
        hidden: s.hidden === true || t.hidden === true,
      });
    }

    // Agent-action trail (numbered overlay edges in the visiting accent).
    if (showTrail && overlay.order.length > 1) {
      for (let i = 1; i < overlay.order.length; i++) {
        const a = overlay.order[i - 1];
        const b = overlay.order[i];
        if (a === b) continue;
        const na = byId.get(a);
        const nb = byId.get(b);
        if (!na || !nb) continue;
        const sys = overlay.visitedBy.get(b) ?? 'A';
        const col = SYSTEM_META[sys].color;
        edges.push({
          id: `trail-${i}`,
          source: a,
          target: b,
          type: 'smoothstep',
          className: 'ge edge-trail',
          animated: true,
          zIndex: 6,
          label: String(overlay.trailNo.get(b) ?? i),
          labelStyle: { fill: col, fontSize: 10, fontWeight: 700 },
          labelBgStyle: { fill: '#0b0f17', fillOpacity: 0.9 },
          style: { stroke: col, strokeWidth: 2.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: col, width: 14, height: 14 },
          hidden: na.hidden === true || nb.hidden === true,
        });
      }
    }
    return edges;
  }, [data, rfNodes, overlay, showTrail]);

  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of data?.nodes ?? []) {
      counts.set(n.kind, (counts.get(n.kind) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);

  // --------------------------------------------------------------- actions
  const centerOn = useCallback(
    (id: string) => {
      const p = posRef.current[id];
      if (p) void rf.setCenter(p.x, p.y, { zoom: 1.15, duration: 600 });
    },
    [rf],
  );

  const selectNode = useCallback(
    async (id: string) => {
      if (!repoId) return;
      setDetail(null);
      setDetailErr(null);
      setDetailLoading(true);
      try {
        const d = await api.getGraphNode(repoId, id);
        setDetail(d);
        // Make sure the node's kind isn't filtered out, then centre on it.
        const kind = d?.node?.kind;
        if (kind) {
          setDisabledKinds((prev) => {
            if (!prev.has(kind)) return prev;
            const next = new Set(prev);
            next.delete(kind);
            return next;
          });
        }
        centerOn(id);
      } catch (e) {
        setDetailErr(errMsg(e));
      } finally {
        setDetailLoading(false);
      }
    },
    [repoId, centerOn],
  );

  const doSearch = useCallback(async () => {
    if (!repoId) return;
    const q = query.trim();
    if (!q) {
      setResults(null);
      setSearchErr(null);
      return;
    }
    setSearching(true);
    setSearchErr(null);
    try {
      const hits = await api.searchGraph(repoId, q);
      setResults(hits);
      if (hits.length > 0) {
        // Centre on the best match immediately.
        void selectNode(hits[0].id);
      }
    } catch (e) {
      setSearchErr(errMsg(e));
    } finally {
      setSearching(false);
    }
  }, [repoId, query, selectNode]);

  const toggleKind = (kind: string) => {
    setDisabledKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  const clearOverlay = () => {
    setOverlayRunId('');
    setOverlayEvents(null);
    setScrub(0);
    setScrubMax(0);
    setOverlayErr(null);
  };

  // ---------------------------------------------------------------- render
  const overlayActive = overlayRunId !== '';
  const visitedCount = overlay.visitedBy.size;

  return (
    <div className={`graph-view ${detail || detailLoading ? 'with-side' : ''}`}>
      <div className="graph-main">
        <div className="graph-toolbar">
          <label className="label" htmlFor="graph-repo">
            Repo
          </label>
          <select
            id="graph-repo"
            className="select"
            value={repoId ?? ''}
            onChange={(e) => setRepoId(e.target.value || null)}
          >
            <option value="" disabled>
              {reposErr ? 'repos unavailable' : 'Select a repository…'}
            </option>
            {(repos ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>

          {gstatus && (
            <span
              className={`pill pill-${
                gstatus.status === 'ready'
                  ? 'success'
                  : gstatus.status === 'building'
                    ? 'running'
                    : gstatus.status === 'error'
                      ? 'danger'
                      : 'neutral'
              }`}
            >
              graph: {gstatus.status}
            </span>
          )}

          <div className="graph-search">
            <input
              className="input"
              placeholder="Search nodes (name / symbol)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void doSearch();
              }}
            />
            <button
              type="button"
              className="btn btn-sm"
              disabled={searching || !repoId}
              onClick={() => void doSearch()}
            >
              {searching ? '…' : 'Search'}
            </button>
            {results && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setResults(null)}>
                ✕
              </button>
            )}
          </div>
        </div>

        {searchErr && <ErrorBanner message={searchErr} />}

        {results && results.length > 0 && (
          <div className="search-results" role="listbox" aria-label="Search results">
            {results.slice(0, 50).map((n) => (
              <button
                key={n.id}
                type="button"
                className="search-hit"
                onClick={() => void selectNode(n.id)}
              >
                <span className={`swatch swatch-node n-${n.kind}`} aria-hidden="true" />
                <span className="mono">{n.label}</span>
                <span className="muted small">
                  {n.kind}
                  {n.file ? ` · ${n.file}${n.line != null ? `:${n.line}` : ''}` : ''}
                </span>
              </button>
            ))}
          </div>
        )}
        {results && results.length === 0 && (
          <div className="hint muted small">No nodes matched “{query}”.</div>
        )}

        {/* kind filter chips */}
        {kinds.length > 0 && (
          <div className="kind-chips">
            <span className="label">kinds:</span>
            {kinds.map(([k, count]) => (
              <button
                key={k}
                type="button"
                className={`kind-chip ${disabledKinds.has(k) ? 'off' : 'on'}`}
                aria-pressed={!disabledKinds.has(k)}
                onClick={() => toggleKind(k)}
              >
                <span className={`swatch swatch-node n-${k}`} aria-hidden="true" />
                {k} <span className="muted">{count}</span>
              </button>
            ))}
          </div>
        )}

        {/* run overlay controls */}
        <div className="overlay-bar">
          <label className="label" htmlFor="overlay-run">
            Run overlay
          </label>
          <select
            id="overlay-run"
            className="select"
            value={overlayRunId}
            onChange={(e) => setOverlayRunId(e.target.value)}
          >
            <option value="">— none —</option>
            {(runs ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} · {r.repo_name} · {r.task.slice(0, 36)}
              </option>
            ))}
          </select>
          <select
            className="select select-sys"
            value={overlaySys}
            onChange={(e) => setOverlaySys(e.target.value as SystemID | 'all')}
            disabled={!overlayActive}
          >
            <option value="all">all systems</option>
            <option value="A">A · Standard</option>
            <option value="B">B · Graph-Augmented</option>
            <option value="C">C · GNN-Enhanced</option>
          </select>
          <button
            type="button"
            className={`btn btn-sm ${showTrail ? 'btn-primary' : ''}`}
            disabled={!overlayActive}
            aria-pressed={showTrail}
            onClick={() => setShowTrail((v) => !v)}
          >
            Show trail
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={!overlayActive}
            onClick={clearOverlay}
          >
            Clear
          </button>
          {overlayLoading && <span className="muted small">loading events…</span>}
          {overlayErr && <span className="form-error">{overlayErr}</span>}
          {overlayActive && !overlayLoading && !overlayErr && (
            <span className="muted small">
              {visitedCount} node{visitedCount === 1 ? '' : 's'} visited
            </span>
          )}
        </div>

        {overlayActive && scrubMax > 0 && (
          <div className="scrubber">
            <span className="label">timeline</span>
            <input
              type="range"
              min={0}
              max={scrubMax}
              value={scrub}
              onChange={(e) => setScrub(Number(e.target.value))}
              aria-label="Event timeline scrubber"
            />
            <span className="mono small muted">seq ≤ {scrub} / {scrubMax}</span>
          </div>
        )}

        <div className="graph-canvas">
          {reposErr && <ErrorBanner message={reposErr} />}
          {!reposErr && !repoId && (
            <EmptyState
              title="Select a repository"
              hint="Load a repository to explore its code knowledge graph."
            />
          )}
          {repoId && dataLoading && <Spinner label="Loading graph…" />}
          {repoId && !dataLoading && dataErr && (
            <ErrorBanner message={dataErr} onRetry={() => setDataTick((t) => t + 1)} />
          )}
          {repoId && !dataLoading && !dataErr && data && (data.nodes ?? []).length === 0 && (
            <EmptyState
              title="Graph has no nodes"
              hint="Build the knowledge graph from the Repository Workspace tab."
            />
          )}
          {repoId && !dataLoading && !dataErr && data && (data.nodes ?? []).length > 0 && (
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={NODE_TYPES}
              onNodeClick={(_e, node) => void selectNode(node.id)}
              fitView
              minZoom={0.05}
              maxZoom={2}
              nodesDraggable={false}
              nodesConnectable={false}
              deleteKeyCode={null}
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#1f2937" />
              <Controls showInteractive={false} />
              <MiniMap
                pannable
                zoomable
                nodeColor={(n) => kindColor((n.data as GNodeData)?.kind ?? '')}
                maskColor="rgba(11,15,23,0.75)"
              />
            </ReactFlow>
          )}
        </div>

        {/* legend */}
        <div className="legend">
          <span className="legend-title">nodes</span>
          {['module', 'function', 'class', 'test_function'].map((k) => (
            <span key={k} className="legend-item">
              <span className={`swatch swatch-node n-${k}`} aria-hidden="true" />
              {k}
            </span>
          ))}
          <span className="legend-sep" />
          <span className="legend-title">edges</span>
          {EDGE_TYPES.map((t) => (
            <span key={t} className="legend-item">
              <span className={`swatch swatch-edge e-${t}`} aria-hidden="true" />
              {t}
            </span>
          ))}
          <span className="legend-sep" />
          <span className="legend-item">
            <span className="swatch swatch-dashed" aria-hidden="true" />
            GNN prediction (dashed)
          </span>
          <span className="legend-item">
            <span className="swatch swatch-visited" aria-hidden="true" />
            agent visit (accent)
          </span>
          <span className="legend-item">
            <span className="swatch swatch-edited" aria-hidden="true" />
            edited file (orange)
          </span>
          <span className="legend-item">
            <span className="swatch swatch-trail" aria-hidden="true" />
            agent action trail
          </span>
        </div>
      </div>

      {/* ------------------------------------------------------ side panel */}
      {(detail || detailLoading || detailErr) && (
        <aside className="graph-side">
          <header className="side-head">
            <span className="side-title mono">{detail?.node?.label ?? 'node'}</span>
            <button
              type="button"
              className="btn btn-sm close-x"
              aria-label="Close node details"
              onClick={() => {
                setDetail(null);
                setDetailErr(null);
              }}
            >
              ✕
            </button>
          </header>

          {detailLoading && <Spinner label="Loading node…" />}
          {detailErr && <ErrorBanner message={detailErr} />}
          {detail && (
            <div className="side-body">
              <div className="chip-row">
                <span className="pill pill-info">{detail.node.kind}</span>
                {detail.node.test && <span className="pill pill-neutral">test</span>}
                {detail.node.gnn_score != null && (
                  <span className="pill pill-success" title="GNN impact score">
                    GNN score {detail.node.gnn_score.toFixed(2)}
                  </span>
                )}
                {detail.node.gnn_impact != null && (
                  <span className="pill pill-warn" title="GNN impact">
                    impact {detail.node.gnn_impact.toFixed(2)}
                  </span>
                )}
              </div>

              <dl className="meta-grid compact">
                <div>
                  <dt>file</dt>
                  <dd className="mono small">{detail.node.file ?? '—'}</dd>
                </div>
                <div>
                  <dt>line</dt>
                  <dd className="mono small">{detail.node.line ?? '—'}</dd>
                </div>
                <div>
                  <dt>loc</dt>
                  <dd>{detail.node.loc ?? '—'}</dd>
                </div>
              </dl>

              {!!detail.callers?.length && (
                <div className="side-section">
                  <div className="subhead">Callers ({detail.callers.length})</div>
                  <div className="ref-list">
                    {detail.callers.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        className="ref-chip mono"
                        onClick={() => void selectNode(c.id)}
                      >
                        ← {c.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {!!detail.callees?.length && (
                <div className="side-section">
                  <div className="subhead">Callees ({detail.callees.length})</div>
                  <div className="ref-list">
                    {detail.callees.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        className="ref-chip mono"
                        onClick={() => void selectNode(c.id)}
                      >
                        → {c.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {!!detail.related?.length && (
                <div className="side-section">
                  <div className="subhead">Related ({detail.related.length})</div>
                  <div className="ref-list">
                    {detail.related.map((r, i) => (
                      <button
                        key={`${r.id}-${i}`}
                        type="button"
                        className="ref-chip mono"
                        onClick={() => void selectNode(r.id)}
                      >
                        {r.type ?? 'rel'} · {r.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="side-section">
                <div className="subhead">Source</div>
                {detail.source ? (
                  <pre className="code-pre source-pre">{detail.source}</pre>
                ) : (
                  <p className="muted small">No source slice available for this node.</p>
                )}
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

export default function GraphExplorer() {
  return (
    <ReactFlowProvider>
      <Explorer />
    </ReactFlowProvider>
  );
}
