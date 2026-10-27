import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import type {
  CreateRunInput,
  FileContent,
  GraphStatusResponse,
  RepoDetail,
  RepoSummary,
  SystemID,
  TreeNode,
} from '../api/types';
import {
  EmptyState,
  ErrorBanner,
  Panel,
  Spinner,
  SYSTEM_META,
  SYSTEM_ORDER,
  fmtBytes,
  fmtDate,
} from '../components/ui';

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

interface Props {
  onRunCreated: (runId: string) => void;
}

// ---------------------------------------------------------------------------
// File tree (recursive)
// ---------------------------------------------------------------------------

function TreeChildren({
  nodes,
  depth,
  expanded,
  onToggle,
  activePath,
  onOpen,
}: {
  nodes: TreeNode[];
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  activePath: string | null;
  onOpen: (path: string) => void;
}) {
  return (
    <ul className="tree-children">
      {nodes.map((n) =>
        n.type === 'dir' ? (
          <li key={n.path || n.name}>
            <button
              type="button"
              className="tree-row tree-dir"
              style={{ paddingLeft: 6 + depth * 14 }}
              aria-expanded={expanded.has(n.path)}
              onClick={() => onToggle(n.path)}
            >
              <span className="tree-caret" aria-hidden="true">
                {expanded.has(n.path) ? '▾' : '▸'}
              </span>
              <span className="tree-name">{n.name}</span>
            </button>
            {expanded.has(n.path) && n.children && n.children.length > 0 && (
              <TreeChildren
                nodes={n.children}
                depth={depth + 1}
                expanded={expanded}
                onToggle={onToggle}
                activePath={activePath}
                onOpen={onOpen}
              />
            )}
          </li>
        ) : (
          <li key={n.path || n.name}>
            <button
              type="button"
              className={`tree-row tree-file ${activePath === n.path ? 'active' : ''}`}
              style={{ paddingLeft: 6 + depth * 14 }}
              onClick={() => onOpen(n.path)}
            >
              <span className="tree-caret" aria-hidden="true">
                ·
              </span>
              <span className="tree-name">{n.name}</span>
              {n.bytes != null && <span className="tree-size">{fmtBytes(n.bytes)}</span>}
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

export default function Workspace({ onRunCreated }: Props) {
  // Repositories ------------------------------------------------------------
  const [repos, setRepos] = useState<RepoSummary[] | null>(null);
  const [reposErr, setReposErr] = useState<string | null>(null);
  const [reposLoading, setReposLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [repo, setRepo] = useState<RepoDetail | null>(null);
  const [repoErr, setRepoErr] = useState<string | null>(null);
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoTick, setRepoTick] = useState(0);

  // Ingest ------------------------------------------------------------------
  const [ingestErr, setIngestErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [ghUrl, setGhUrl] = useState('');
  const [ghBranch, setGhBranch] = useState('');
  const [ghBusy, setGhBusy] = useState(false);

  // Files -------------------------------------------------------------------
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['']));
  const [activePath, setActivePath] = useState<string | null>(null);
  const [file, setFile] = useState<FileContent | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const fileReqRef = useRef(0);

  // Graph -------------------------------------------------------------------
  const [graph, setGraph] = useState<GraphStatusResponse | null>(null);
  const [graphErr, setGraphErr] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  // Run form ----------------------------------------------------------------
  const [task, setTask] = useState('');
  const [systems, setSystems] = useState<SystemID[]>(['A', 'B', 'C']);
  const [advOpen, setAdvOpen] = useState(false);
  const [adv, setAdv] = useState({
    max_iterations: '3',
    tool_call_budget: '60',
    token_budget: '60000',
    timeout_sec: '600',
    model: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  // ------------------------------------------------------------------ loads
  const loadRepos = useCallback(async () => {
    setReposLoading(true);
    setReposErr(null);
    try {
      setRepos(await api.listRepos());
    } catch (e) {
      setReposErr(errMsg(e));
    } finally {
      setReposLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRepos();
  }, [loadRepos]);

  // Load repo detail + graph status whenever the selection changes.
  useEffect(() => {
    setRepo(null);
    setRepoErr(null);
    setGraph(null);
    setGraphErr(null);
    setActivePath(null);
    setFile(null);
    setFileErr(null);
    setExpanded(new Set(['']));
    if (!selectedId) return;
    let cancelled = false;
    setRepoLoading(true);
    (async () => {
      try {
        const [d, g] = await Promise.all([
          api.getRepo(selectedId),
          api.getGraph(selectedId),
        ]);
        if (cancelled) return;
        setRepo(d);
        setGraph(g);
      } catch (e) {
        if (!cancelled) setRepoErr(errMsg(e));
      } finally {
        if (!cancelled) setRepoLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, repoTick]);

  // Poll GET /api/repos/{id}/graph every 1.5s while building.
  useEffect(() => {
    const id = selectedId;
    if (!id || graph?.status !== 'building') return;
    const iv = window.setInterval(() => {
      api
        .getGraph(id)
        .then((g) => {
          setGraph(g);
          setRepos((prev) =>
            prev ? prev.map((r) => (r.id === id ? { ...r, graph_status: g.status } : r)) : prev,
          );
        })
        .catch(() => {
          /* transient poll failure — keep trying */
        });
    }, 1500);
    return () => window.clearInterval(iv);
  }, [selectedId, graph?.status]);

  // ------------------------------------------------------------------ ingest
  const handleZip = async (f: File | null) => {
    if (!f || uploading) return;
    setIngestErr(null);
    setUploading(true);
    try {
      const created = await api.uploadRepo(f);
      await loadRepos();
      setSelectedId(created.id);
    } catch (e) {
      setIngestErr(errMsg(e));
    } finally {
      setUploading(false);
    }
  };

  const connectGithub = async () => {
    if (ghBusy) return;
    setIngestErr(null);
    if (!ghUrl.trim()) {
      setIngestErr('Repository URL is required.');
      return;
    }
    setGhBusy(true);
    try {
      const created = await api.addGithubRepo(ghUrl.trim(), ghBranch);
      await loadRepos();
      setSelectedId(created.id);
      setGhUrl('');
      setGhBranch('');
    } catch (e) {
      setIngestErr(errMsg(e));
    } finally {
      setGhBusy(false);
    }
  };

  // ------------------------------------------------------------------- files
  const toggleDir = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const openFile = async (path: string) => {
    if (!selectedId) return;
    const req = ++fileReqRef.current;
    setActivePath(path);
    setFile(null);
    setFileErr(null);
    setFileLoading(true);
    try {
      const fc = await api.getRepoFile(selectedId, path);
      if (req === fileReqRef.current) setFile(fc);
    } catch (e) {
      if (req === fileReqRef.current) setFileErr(errMsg(e));
    } finally {
      if (req === fileReqRef.current) setFileLoading(false);
    }
  };

  // ------------------------------------------------------------------- graph
  const buildGraph = async () => {
    if (!selectedId || building) return;
    setGraphErr(null);
    setBuilding(true);
    try {
      await api.buildGraph(selectedId);
      setGraph({ status: 'building', stats: graph?.stats ?? null, error: null });
      setRepos((prev) =>
        prev ? prev.map((r) => (r.id === selectedId ? { ...r, graph_status: 'building' } : r)) : prev,
      );
    } catch (e) {
      setGraphErr(errMsg(e));
    } finally {
      setBuilding(false);
    }
  };

  // -------------------------------------------------------------- run submit
  const graphReady = graph?.status === 'ready';
  const needsGraph = systems.some((s) => s !== 'A');

  const toggleSystem = (s: SystemID) => {
    setSystems((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : SYSTEM_ORDER.filter((x) => prev.includes(x) || x === s),
    );
  };

  const numOr = (raw: string, dflt: number): number => {
    const n = parseInt(raw, 10);
    return Number.isFinite(n) && n > 0 ? n : dflt;
  };

  const submit = async () => {
    setFormErr(null);
    if (!selectedId) {
      setFormErr('Select a repository first.');
      return;
    }
    if (!task.trim()) {
      setFormErr('Describe the task to run.');
      return;
    }
    if (systems.length === 0) {
      setFormErr('Select at least one system (A / B / C).');
      return;
    }
    setSubmitting(true);
    try {
      const input: CreateRunInput = {
        repo_id: selectedId,
        task: task.trim(),
        systems,
        settings: {
          max_iterations: numOr(adv.max_iterations, 3),
          tool_call_budget: numOr(adv.tool_call_budget, 60),
          token_budget: numOr(adv.token_budget, 60000),
          timeout_sec: numOr(adv.timeout_sec, 600),
          model: adv.model.trim() ? adv.model.trim() : null,
        },
      };
      const run = await api.createRun(input);
      onRunCreated(run.id);
    } catch (e) {
      // e.g. 400 "graph not ready — build the graph first for systems B/C"
      setFormErr(errMsg(e));
    } finally {
      setSubmitting(false);
    }
  };

  // ------------------------------------------------------------------ render
  const g = graph;
  const stats = g?.stats ?? null;

  return (
    <div className="workspace-grid">
      {/* ------------------------------------------------------------------ */}
      {/* Column 1 — repositories + ingest                                    */}
      {/* ------------------------------------------------------------------ */}
      <div className="ws-col ws-col-left">
        <Panel
          title="Repositories"
          right={
            <button type="button" className="btn btn-sm" onClick={() => void loadRepos()}>
              ↻ refresh
            </button>
          }
        >
          <div className="ingest">
            <label className="label" htmlFor="zip-input">
              Upload .zip
            </label>
            <div className="upload-row">
              <input
                id="zip-input"
                type="file"
                accept=".zip,application/zip"
                className="input input-file"
                onChange={(e) => void handleZip(e.target.files?.[0] ?? null)}
              />
            </div>

            <label className="label" htmlFor="gh-url">
              GitHub URL
            </label>
            <input
              id="gh-url"
              className="input"
              placeholder="https://github.com/org/repo"
              value={ghUrl}
              onChange={(e) => setGhUrl(e.target.value)}
            />
            <input
              className="input"
              placeholder="branch (optional, e.g. main)"
              value={ghBranch}
              onChange={(e) => setGhBranch(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-block"
              disabled={ghBusy || uploading}
              onClick={() => void connectGithub()}
            >
              {ghBusy ? 'Cloning…' : 'Connect GitHub repo'}
            </button>

            {uploading && (
              <div className="spinner-row">
                <span className="spinner spinner-sm" aria-hidden="true" />
                <span className="muted">Uploading archive…</span>
              </div>
            )}
            {ingestErr && <div className="form-error">{ingestErr}</div>}
          </div>

          <div className="repo-list" role="listbox" aria-label="Repositories">
            {reposLoading && <Spinner label="Loading repositories…" />}
            {reposErr && <ErrorBanner message={reposErr} onRetry={() => void loadRepos()} />}
            {!reposLoading && !reposErr && repos && repos.length === 0 && (
              <EmptyState
                title="No repositories yet"
                hint="Upload a .zip archive or connect a GitHub repository to get started."
              />
            )}
            {!reposLoading &&
              repos &&
              repos.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="option"
                  aria-selected={selectedId === r.id}
                  className={`repo-item ${selectedId === r.id ? 'active' : ''}`}
                  onClick={() => setSelectedId(r.id)}
                >
                  <div className="repo-item-top">
                    <span className="repo-name">{r.name}</span>
                    <span className={`graph-dot gs-${r.graph_status}`} title={`graph: ${r.graph_status}`} />
                  </div>
                  <div className="repo-item-sub muted">
                    <span className="tag">{r.source_type}</span>
                    <span>{r.file_count} files</span>
                  </div>
                </button>
              ))}
          </div>
        </Panel>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Column 2 — repo detail + graph                                     */}
      {/* ------------------------------------------------------------------ */}
      <div className="ws-col ws-col-mid">
        {!selectedId && (
          <Panel title="Repository">
            <EmptyState
              title="No repository selected"
              hint="Pick a repository on the left, or ingest a new one."
            />
          </Panel>
        )}

        {selectedId && repoLoading && (
          <Panel title="Repository">
            <Spinner label="Loading repository…" />
          </Panel>
        )}

        {selectedId && repoErr && (
          <Panel title="Repository">
            <ErrorBanner message={repoErr} onRetry={() => setRepoTick((t) => t + 1)} />
          </Panel>
        )}

        {selectedId && !repoLoading && !repoErr && repo && (
          <Panel
            title={<span className="mono">{repo.name}</span>}
            right={<span className="muted small">{repo.id}</span>}
          >
            <dl className="meta-grid">
              <div>
                <dt>Source</dt>
                <dd>
                  <span className="tag">{repo.source_type}</span>{' '}
                  {repo.origin_url ? <span className="mono small">{repo.origin_url}</span> : <span className="muted">—</span>}
                </dd>
              </div>
              <div>
                <dt>Branch / commit</dt>
                <dd className="mono small">
                  {repo.default_branch ?? '—'} / {repo.commit ?? '—'}
                </dd>
              </div>
              <div>
                <dt>Files / size</dt>
                <dd>
                  {repo.file_count} · {fmtBytes(repo.total_bytes)}
                </dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{fmtDate(repo.created_at)}</dd>
              </div>
              <div>
                <dt>Languages</dt>
                <dd className="lang-chips">
                  {Object.entries(repo.languages ?? {}).map(([lang, n]) => (
                    <span key={lang} className="tag">
                      {lang} {n}
                    </span>
                  ))}
                  {Object.keys(repo.languages ?? {}).length === 0 && <span className="muted">—</span>}
                </dd>
              </div>
            </dl>

            <div className="file-split">
              <div className="file-tree-wrap">
                <div className="subhead">Files</div>
                <div className="file-tree">
                  {repo.tree && repo.tree.type === 'dir' && repo.tree.children ? (
                    <TreeChildren
                      nodes={repo.tree.children}
                      depth={0}
                      expanded={expanded}
                      onToggle={toggleDir}
                      activePath={activePath}
                      onOpen={(p) => void openFile(p)}
                    />
                  ) : repo.tree && repo.tree.type === 'file' ? (
                    <TreeChildren
                      nodes={[repo.tree]}
                      depth={0}
                      expanded={expanded}
                      onToggle={toggleDir}
                      activePath={activePath}
                      onOpen={(p) => void openFile(p)}
                    />
                  ) : (
                    <div className="muted small">Empty repository.</div>
                  )}
                </div>
              </div>

              <div className="file-viewer-wrap">
                <div className="subhead">
                  {activePath ? <span className="mono">{activePath}</span> : 'File viewer'}
                  {file?.truncated && <span className="pill pill-warn">truncated</span>}
                </div>
                <div className="file-viewer">
                  {!activePath && (
                    <EmptyState title="Select a file" hint="Choose a file from the tree to preview it." />
                  )}
                  {activePath && fileLoading && <Spinner label="Loading file…" />}
                  {activePath && !fileLoading && fileErr && <ErrorBanner message={fileErr} />}
                  {activePath && !fileLoading && !fileErr && file && (
                    <pre className="code-pre">{file.content}</pre>
                  )}
                </div>
              </div>
            </div>
          </Panel>
        )}

        {selectedId && !repoLoading && !repoErr && (
          <Panel
            title="Knowledge graph"
            right={
              g ? (
                <span className={`pill pill-${g.status === 'ready' ? 'success' : g.status === 'building' ? 'running' : g.status === 'error' ? 'danger' : 'neutral'}`}>
                  graph: {g.status}
                </span>
              ) : null
            }
          >
            {!g && <Spinner label="Loading graph status…" />}
            {g && (
              <div className="graph-card">
                {g.status === 'building' && (
                  <div className="spinner-row">
                    <span className="spinner spinner-sm" aria-hidden="true" />
                    <span className="muted">Building graph — polling GET /api/repos/{selectedId}/graph…</span>
                  </div>
                )}

                {g.status === 'ready' && stats && (
                  <div className="graph-stats">
                    <div className="stat-row">
                      <div className="stat">
                        <span className="stat-value">{stats.nodes}</span>
                        <span className="stat-label">nodes</span>
                      </div>
                      <div className="stat">
                        <span className="stat-value">{stats.edges}</span>
                        <span className="stat-label">edges</span>
                      </div>
                      <div className="stat">
                        <span className="stat-value small">{stats.built_at ? fmtDate(stats.built_at) : '—'}</span>
                        <span className="stat-label">built at</span>
                      </div>
                    </div>
                    <div className="chip-row">
                      {Object.entries(stats.by_kind ?? {}).map(([k, v]) => (
                        <span key={k} className={`legend-chip kind-${k}`}>
                          <span className={`swatch swatch-node n-${k}`} aria-hidden="true" />
                          {k} · {v}
                        </span>
                      ))}
                    </div>
                    <div className="chip-row">
                      {Object.entries(stats.by_edge ?? {}).map(([k, v]) => (
                        <span key={k} className="legend-chip">
                          <span className={`swatch swatch-edge e-${k}`} aria-hidden="true" />
                          {k} · {v}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {g.status === 'absent' && (
                  <p className="muted">
                    No graph for this repository yet. Systems B (Graph-Augmented) and C
                    (GNN-Enhanced) require a built graph.
                  </p>
                )}

                {g.status === 'error' && (
                  <div className="form-error">Graph build failed: {g.error ?? 'unknown error'}</div>
                )}
                {graphErr && <div className="form-error">{graphErr}</div>}

                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={building || g.status === 'building'}
                  onClick={() => void buildGraph()}
                >
                  {g.status === 'building' ? 'Building…' : g.status === 'ready' ? 'Rebuild graph' : 'Build Graph'}
                </button>
              </div>
            )}
          </Panel>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Column 3 — run configuration                                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="ws-col ws-col-right">
        <Panel title="New run">
          <label className="label" htmlFor="task-input">
            Task
          </label>
          <textarea
            id="task-input"
            className="textarea"
            rows={7}
            placeholder="e.g. Fix the validation bug in create_order so negative quantities are rejected."
            value={task}
            onChange={(e) => setTask(e.target.value)}
          />

          <div className="label">Systems</div>
          <div className="sys-checks">
            {SYSTEM_ORDER.map((s) => (
              <label key={s} className={`sys-check sys-${s}`}>
                <input
                  type="checkbox"
                  checked={systems.includes(s)}
                  onChange={() => toggleSystem(s)}
                />
                <span className="sys-check-letter" style={{ color: SYSTEM_META[s].color }}>
                  {s}
                </span>
                <span>
                  {s} · {SYSTEM_META[s].name}
                </span>
              </label>
            ))}
          </div>
          <p className="hint muted small">{SYSTEM_ORDER.map((s) => SYSTEM_META[s].desc).join(' ')}</p>

          {needsGraph && !graphReady && (
            <div className="hint hint-warn">
              Systems B / C need a built graph — run “Build Graph” above first (or deselect them).
              The API will answer 400 until the graph is ready.
            </div>
          )}

          <button
            type="button"
            className={`adv-toggle ${advOpen ? 'open' : ''}`}
            aria-expanded={advOpen}
            onClick={() => setAdvOpen((v) => !v)}
          >
            <span className="tree-caret" aria-hidden="true">
              {advOpen ? '▾' : '▸'}
            </span>
            Advanced settings
          </button>
          {advOpen && (
            <div className="adv-body">
              <div className="form-grid">
                <label className="field">
                  <span className="label">max_iterations</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    value={adv.max_iterations}
                    onChange={(e) => setAdv((a) => ({ ...a, max_iterations: e.target.value }))}
                  />
                </label>
                <label className="field">
                  <span className="label">tool_call_budget</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    value={adv.tool_call_budget}
                    onChange={(e) => setAdv((a) => ({ ...a, tool_call_budget: e.target.value }))}
                  />
                </label>
                <label className="field">
                  <span className="label">token_budget</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    value={adv.token_budget}
                    onChange={(e) => setAdv((a) => ({ ...a, token_budget: e.target.value }))}
                  />
                </label>
                <label className="field">
                  <span className="label">timeout_sec</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    value={adv.timeout_sec}
                    onChange={(e) => setAdv((a) => ({ ...a, timeout_sec: e.target.value }))}
                  />
                </label>
              </div>
              <label className="field">
                <span className="label">model override</span>
                <input
                  className="input"
                  placeholder="server default"
                  value={adv.model}
                  onChange={(e) => setAdv((a) => ({ ...a, model: e.target.value }))}
                />
              </label>
              <p className="muted small">
                Defaults: max_iterations 3 · tool_call_budget 60 · token_budget 60000 · timeout_sec 600
              </p>
            </div>
          )}

          {formErr && (
            <div className="form-error" role="alert">
              {formErr}
            </div>
          )}

          <button
            type="button"
            className="btn btn-primary btn-block btn-lg"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? 'Starting run…' : 'Start run'}
          </button>
          <p className="muted small">
            POST /api/runs — starts execution immediately, then jumps to the Live Execution tab.
          </p>
        </Panel>
      </div>
    </div>
  );
}
