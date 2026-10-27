import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { api, ApiError } from '../api/client';
import type {
  RunDetail,
  RunEvent,
  RunMetrics,
  RunSummary,
  SystemDetail,
  SystemID,
} from '../api/types';
import {
  CompletionBadge,
  EmptyState,
  ErrorBanner,
  Modal,
  Spinner,
  StageStepper,
  StatusPill,
  SYSTEM_META,
  SYSTEM_ORDER,
  fmtCost,
  fmtDuration,
  fmtNum,
  fmtTime,
} from '../components/ui';

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
function isTerminal(status: string | null | undefined): boolean {
  return !!status && TERMINAL.has(status);
}

type LiveMetrics = Partial<Record<SystemID, Partial<RunMetrics>>>;

// ---------------------------------------------------------------------------
// Diff rendering
// ---------------------------------------------------------------------------

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) {
    return 'diff-line diff-meta';
  }
  if (line.startsWith('@@')) return 'diff-line diff-hunk';
  if (line.startsWith('+')) return 'diff-line diff-add';
  if (line.startsWith('-')) return 'diff-line diff-del';
  return 'diff-line';
}

function DiffView({ diff }: { diff: string | null | undefined }) {
  if (!diff) return <p className="muted small">No diff recorded.</p>;
  const lines = diff.split('\n');
  return (
    <pre className="diff-pre" aria-label="diff">
      {lines.map((l, i) => (
        <div key={i} className={diffLineClass(l)}>
          {l || ' '}
        </div>
      ))}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Event feed
// ---------------------------------------------------------------------------

function EventRow({ ev }: { ev: RunEvent }) {
  const [open, setOpen] = useState(false);
  const p: Record<string, any> = ev.payload ?? {};
  const type = ev.type;
  const time = fmtTime(ev.ts);

  if (type === 'metric_update') return null; // metrics are rendered in the header silently

  let summary: ReactNode = <span className="event-summary">{type}</span>;
  let detail: React.ReactNode = null;
  let expandable = false;

  switch (type) {
    case 'tool_call': {
      expandable = true;
      summary = (
        <>
          <span className="event-verb">call</span>
          <span className="event-summary mono">{String(p.tool ?? '?')}</span>
          {p.agent && <span className="event-agent">{p.agent}</span>}
        </>
      );
      detail = <pre className="event-detail">{JSON.stringify(p.args ?? {}, null, 2)}</pre>;
      break;
    }
    case 'tool_result': {
      expandable = true;
      summary = (
        <>
          <span className={`event-verb ${p.ok ? 'ok' : 'bad'}`}>{p.ok ? 'result ✓' : 'result ✗'}</span>
          <span className="event-summary mono">{String(p.tool ?? '?')}</span>
          <span className="event-meta">{fmtDuration(p.duration_ms)}</span>
        </>
      );
      detail = (
        <pre className="event-detail">{p.preview ? String(p.preview) : '— no preview —'}</pre>
      );
      break;
    }
    case 'plan_generated': {
      const steps = Array.isArray(p.steps) ? p.steps : [];
      expandable = true;
      summary = (
        <>
          <span className="event-verb">plan</span>
          <span className="event-summary">{steps.length} steps</span>
        </>
      );
      detail = (
        <ol className="plan-steps">
          {steps.map((s: any, i: number) => (
            <li key={String(s?.id ?? i)}>
              <div className="plan-desc">{String(s?.description ?? '')}</div>
              {Array.isArray(s?.files) && s.files.length > 0 && (
                <div className="plan-files mono small">{s.files.join(', ')}</div>
              )}
            </li>
          ))}
        </ol>
      );
      break;
    }
    case 'edit_applied': {
      summary = (
        <>
          <span className={`edit-action a-${p.action ?? 'modify'}`}>{String(p.action ?? 'edit')}</span>
          <span className="event-summary mono">{String(p.path ?? '?')}</span>
          <span className="diff-stat">
            <span className="add">+{Number(p.additions ?? 0)}</span>{' '}
            <span className="del">−{Number(p.deletions ?? 0)}</span>
          </span>
        </>
      );
      break;
    }
    case 'test_results': {
      const passed = Number(p.passed ?? 0);
      const failed = Number(p.failed ?? 0);
      const failures = Array.isArray(p.failures) ? p.failures : [];
      expandable = true;
      summary = (
        <>
          <span className={`event-verb ${failed > 0 ? 'bad' : 'ok'}`}>
            tests {passed}✓ {failed}✗
          </span>
          {failed > 0 && <span className="event-summary">{failed} failing</span>}
        </>
      );
      detail =
        failures.length > 0 ? (
          <ul className="failure-list">
            {failures.map((f: any, i: number) => (
              <li key={i}>
                <span className="failure-name mono">{String(f?.name ?? `test ${i}`)}</span>
                {f?.file && (
                  <span className="failure-loc mono small">
                    {String(f.file)}
                    {f.line != null ? `:${f.line}` : ''}
                  </span>
                )}
                <pre className="failure-error">{String(f?.error ?? '')}</pre>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">All tests passed.</p>
        );
      break;
    }
    case 'repair_attempt': {
      expandable = true;
      summary = (
        <>
          <span className="event-verb warn">repair</span>
          <span className="event-summary">{String(p.diagnosis ?? 'attempt')}</span>
        </>
      );
      detail = (
        <div className="repair-detail">
          <div>
            <span className="kv-key">root cause:</span> {String(p.root_cause ?? '—')}
          </div>
          <div>
            <span className="kv-key">target stage:</span> {String(p.target_stage ?? '—')}
          </div>
        </div>
      );
      break;
    }
    case 'stage_transition': {
      summary = (
        <>
          <span className="event-verb">stage</span>
          <span className="event-summary">
            {String(p.from ?? '?')} → {String(p.to ?? '?')}
          </span>
          {p.reason && <span className="event-meta">{String(p.reason)}</span>}
        </>
      );
      break;
    }
    case 'stage_started':
    case 'stage_finished': {
      summary = (
        <>
          <span className="event-verb">{type === 'stage_started' ? 'stage ▶' : 'stage ■'}</span>
          <span className="event-summary">{String(p.stage ?? ev.stage ?? '?')}</span>
        </>
      );
      break;
    }
    case 'llm_call': {
      summary = (
        <>
          <span className="event-verb">llm</span>
          <span className="event-summary mono">{String(p.model ?? '?')}</span>
          <span className="event-meta">
            {fmtNum(Number(p.total_tokens ?? 0))} tok · {fmtDuration(Number(p.duration_ms ?? 0))}
          </span>
        </>
      );
      break;
    }
    case 'graph_visit': {
      const ids: string[] = Array.isArray(p.node_ids) ? p.node_ids.map(String) : [];
      expandable = true;
      summary = (
        <>
          <span className="event-verb">graph</span>
          <span className="event-summary">{ids.length} nodes visited</span>
          {p.reason && <span className="event-meta">{String(p.reason)}</span>}
        </>
      );
      detail = (
        <ul className="node-id-list mono small">
          {ids.map((id, i) => (
            <li key={`${id}-${i}`}>{id}</li>
          ))}
        </ul>
      );
      break;
    }
    case 'explore_report': {
      const findings = Array.isArray(p.findings) ? p.findings : [];
      expandable = true;
      summary = (
        <>
          <span className="event-verb">report</span>
          <span className="event-summary">{findings.length} findings</span>
        </>
      );
      detail = (
        <ul className="finding-list">
          {findings.map((f: any, i: number) => (
            <li key={i}>
              <span className="mono small">{String(f?.file ?? '')}</span> — {String(f?.note ?? '')}
            </li>
          ))}
        </ul>
      );
      break;
    }
    case 'log': {
      const lvl = String(p.level ?? 'info');
      summary = (
        <span className={`log-msg log-${lvl}`}>
          <span className="log-level">{lvl}</span> {String(p.message ?? '')}
        </span>
      );
      break;
    }
    case 'error': {
      summary = (
        <span className="log-msg log-error">
          <span className="log-level">error</span> {String(p.message ?? 'unknown error')}
        </span>
      );
      break;
    }
    case 'budget_exceeded': {
      summary = (
        <>
          <span className="event-verb warn">budget</span>
          <span className="event-summary">{String(p.budget ?? '?')} budget exceeded</span>
        </>
      );
      break;
    }
    case 'system_started': {
      summary = (
        <>
          <span className="event-verb ok">system ▶</span>
          <span className="event-meta">{String(p.isolation ?? '')}</span>
        </>
      );
      break;
    }
    case 'system_finished': {
      summary = (
        <>
          <span className="event-verb">system ■</span>
          <span className="event-summary">{String(p.status ?? '')}</span>
          <span className="event-meta">
            {String(p.completion ?? '')} · {fmtDuration(Number(p.duration_ms ?? 0))}
          </span>
        </>
      );
      break;
    }
    case 'run_started': {
      summary = (
        <>
          <span className="event-verb ok">run ▶</span>
          <span className="event-summary">{String(p.task ?? '')}</span>
        </>
      );
      break;
    }
    case 'run_finished': {
      summary = (
        <>
          <span className="event-verb">run ■</span>
          <span className="event-summary">{String(p.status ?? '')}</span>
        </>
      );
      break;
    }
    default: {
      expandable = true;
      summary = <span className="event-summary mono">{type}</span>;
      detail = <pre className="event-detail">{JSON.stringify(p, null, 2)}</pre>;
    }
  }

  return (
    <div
      className={`event ev-${type} ${expandable ? 'clickable' : ''} ${open ? 'open' : ''}`}
      onClick={expandable ? () => setOpen((v) => !v) : undefined}
      role={expandable ? 'button' : undefined}
      tabIndex={expandable ? 0 : undefined}
      onKeyDown={
        expandable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setOpen((v) => !v);
              }
            }
          : undefined
      }
    >
      <div className="event-line">
        <span className="event-time">{time}</span>
        {summary}
        {expandable && (
          <span className="event-chev" aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
        )}
      </div>
      {expandable && open && detail}
    </div>
  );
}

function EventFeed({
  events,
  emptyHint,
}: {
  events: RunEvent[];
  emptyHint: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [events]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  if (events.length === 0) {
    return (
      <div className="event-feed is-empty" ref={ref}>
        <div className="feed-empty muted">{emptyHint}</div>
      </div>
    );
  }
  return (
    <div className="event-feed" ref={ref} onScroll={onScroll}>
      {events.map((e) => (
        <EventRow key={e.seq} ev={e} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-system details modal
// ---------------------------------------------------------------------------

function DetailModal({
  runId,
  system,
  onClose,
}: {
  runId: string;
  system: SystemID;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<SystemDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setDetail(await api.getSystemDetail(runId, system));
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [runId, system]);

  useEffect(() => {
    void load();
  }, [load, tick]);

  const meta = SYSTEM_META[system];
  const head = (
    <span className="modal-sys" style={{ '--accent': meta.color } as CSSProperties}>
      <span className="modal-sys-letter">{system}</span>
      {meta.name} — details
    </span>
  );

  return (
    <Modal title={head} onClose={onClose} wide>
      {loading && <Spinner label="Loading system details…" />}
      {!loading && err && <ErrorBanner message={err} onRetry={() => setTick((t) => t + 1)} />}
      {!loading && !err && detail && (
        <div className="detail-body">
          <div className="detail-status-row">
            <StatusPill status={detail.status} />
            <span className="muted small">
              stage: {detail.stage ?? '—'} · workspace: <span className="mono">{detail.workspace ?? '—'}</span>
            </span>
          </div>

          <section className="detail-section">
            <h3>Explore findings</h3>
            {!detail.explore_report && <p className="muted small">No explore report yet.</p>}
            {detail.explore_report && (
              <>
                <ul className="finding-list">
                  {(detail.explore_report.findings ?? []).map((f, i) => (
                    <li key={i}>
                      <span className="mono small">{f.file}</span> — {f.note}
                    </li>
                  ))}
                </ul>
                {!!detail.explore_report.symbols?.length && (
                  <div className="chip-row">
                    {detail.explore_report.symbols.map((s) => (
                      <span key={s} className="tag mono">
                        {s}
                      </span>
                    ))}
                  </div>
                )}
                {!!detail.explore_report.files_inspected?.length && (
                  <p className="muted small">
                    Files inspected: {detail.explore_report.files_inspected.join(', ')}
                  </p>
                )}
              </>
            )}
          </section>

          <section className="detail-section">
            <h3>Plan</h3>
            {!detail.plan || detail.plan.length === 0 ? (
              <p className="muted small">No plan generated.</p>
            ) : (
              <ol className="plan-steps">
                {detail.plan.map((s, i) => (
                  <li key={String(s.id ?? i)}>
                    <div className="plan-desc">{s.description}</div>
                    {!!s.files?.length && <div className="plan-files mono small">{s.files.join(', ')}</div>}
                    {!!s.symbols?.length && (
                      <div className="plan-files mono small">symbols: {s.symbols.join(', ')}</div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="detail-section">
            <h3>Edits ({detail.edits?.length ?? 0})</h3>
            {!detail.edits?.length && <p className="muted small">No edits applied.</p>}
            {detail.edits?.map((ed, i) => (
              <div key={i} className="edit-block">
                <div className="edit-head">
                  <span className={`edit-action a-${ed.action}`}>{ed.action}</span>
                  <span className="mono">{ed.path}</span>
                  <span className="diff-stat">
                    <span className="add">+{ed.additions}</span> <span className="del">−{ed.deletions}</span>
                  </span>
                </div>
                <DiffView diff={ed.diff} />
              </div>
            ))}
          </section>

          <section className="detail-section">
            <h3>Tests</h3>
            {!detail.test_report && <p className="muted small">No test report yet.</p>}
            {detail.test_report && (
              <>
                <div className="chip-row">
                  <span className="pill pill-success">{detail.test_report.passed} passed</span>
                  <span className={`pill ${detail.test_report.failed > 0 ? 'pill-danger' : 'pill-neutral'}`}>
                    {detail.test_report.failed} failed
                  </span>
                </div>
                {!!detail.test_report.failures?.length && (
                  <ul className="failure-list">
                    {detail.test_report.failures.map((f, i) => (
                      <li key={i}>
                        <span className="failure-name mono">{f.name}</span>
                        {f.file && (
                          <span className="failure-loc mono small">
                            {f.file}
                            {f.line != null ? `:${f.line}` : ''}
                          </span>
                        )}
                        <pre className="failure-error">{f.error}</pre>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>

          <section className="detail-section">
            <h3>Repairs ({detail.repairs?.length ?? 0})</h3>
            {!detail.repairs?.length && <p className="muted small">No repair attempts.</p>}
            {detail.repairs?.map((r, i) => (
              <div key={i} className="repair-block">
                <div>
                  <span className="kv-key">diagnosis:</span> {r.diagnosis}
                </div>
                <div>
                  <span className="kv-key">root cause:</span> {r.root_cause}
                </div>
                <div>
                  <span className="kv-key">target stage:</span> {r.target_stage}
                </div>
              </div>
            ))}
          </section>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Execution view
// ---------------------------------------------------------------------------

export default function Execution({
  runId,
  setRunId,
}: {
  runId: string | null;
  setRunId: (id: string | null) => void;
}) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsErr, setRunsErr] = useState<string | null>(null);
  const [runsLoading, setRunsLoading] = useState(true);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState<LiveMetrics>({});
  const [detailSys, setDetailSys] = useState<SystemID | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelErr, setCancelErr] = useState<string | null>(null);

  const afterRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);

  const appendEvent = useCallback((ev: RunEvent) => {
    setEvents((prev) => {
      if (prev.some((e) => e.seq === ev.seq)) return prev;
      const next = [...prev, ev];
      if (next.length > 1 && next[next.length - 1].seq < next[next.length - 2].seq) {
        next.sort((a, b) => a.seq - b.seq);
      }
      return next.length > 4000 ? next.slice(next.length - 4000) : next;
    });
  }, []);

  // ------------------------------------------------------------- run list
  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsErr(null);
    try {
      setRuns(await api.listRuns());
    } catch (e) {
      setRunsErr(errMsg(e));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  // ------------------------------------------------- run detail + backfill
  useEffect(() => {
    setRun(null);
    setRunErr(null);
    setEvents([]);
    setLive({});
    setCancelErr(null);
    if (!runId) return;
    let cancelled = false;
    (async () => {
      try {
        const [detail, back] = await Promise.all([
          api.getRun(runId),
          api.getRunEvents(runId, 0),
        ]);
        if (cancelled) return;
        setRun(detail);
        const evs = (back?.events ?? []).slice().sort((a, b) => a.seq - b.seq);
        setEvents(evs);
        const nextAfter =
          typeof back?.next_after === 'number'
            ? back.next_after
            : evs.length
              ? evs[evs.length - 1].seq + 1
              : 0;
        afterRef.current = nextAfter;
      } catch (e) {
        if (!cancelled) setRunErr(errMsg(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // Keep the run selector list in sync with the live detail.
  useEffect(() => {
    if (!run) return;
    const summary: RunSummary = {
      id: run.id,
      repo_id: run.repo_id,
      repo_name: run.repo_name,
      task: run.task,
      systems: run.systems.map((s) => s.system),
      status: run.status,
      created_at: run.created_at,
      finished_at: run.finished_at,
    };
    setRuns((prev) => {
      if (!prev) return [summary];
      if (!prev.some((r) => r.id === summary.id)) return [summary, ...prev];
      return prev.map((r) => (r.id === summary.id ? { ...r, status: summary.status } : r));
    });
  }, [run]);

  // ------------------------------------------------------ poll while running
  const runStatus = run?.status;
  useEffect(() => {
    if (!runId || isTerminal(runStatus)) return;
    const iv = window.setInterval(() => {
      api
        .getRun(runId)
        .then((rd) => setRun(rd))
        .catch(() => {
          /* transient poll failure */
        });
    }, 2000);
    return () => window.clearInterval(iv);
  }, [runId, runStatus]);

  // --------------------------------------------------------- live SSE stream
  useEffect(() => {
    if (!runId) return;
    let disposed = false;
    let retry: number | undefined;

    const connect = () => {
      if (disposed) return;
      let es: EventSource;
      try {
        es = new EventSource(api.runEventsSseUrl(runId, afterRef.current));
      } catch {
        if (!disposed) retry = window.setTimeout(connect, 2000);
        return;
      }
      esRef.current = es;

      es.addEventListener('msg', (e) => {
        const raw = (e as MessageEvent<string>).data;
        let ev: RunEvent;
        try {
          ev = JSON.parse(raw) as RunEvent;
        } catch {
          return;
        }
        if (typeof ev?.seq !== 'number') return;
        if (ev.seq > afterRef.current) afterRef.current = ev.seq;
        appendEvent(ev);
        if (ev.type === 'metric_update' && ev.system) {
          const sys = ev.system;
          setLive((prev) => ({
            ...prev,
            [sys]: { ...(prev[sys] ?? {}), ...(ev.payload as Partial<RunMetrics>) },
          }));
        }
      });

      es.addEventListener('end', () => {
        es.close();
        if (esRef.current === es) esRef.current = null;
      });

      es.onerror = () => {
        es.close();
        if (esRef.current === es) esRef.current = null;
        if (disposed) return;
        // Reconnect from the last seen seq after a short delay.
        retry = window.setTimeout(connect, 1500);
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retry) window.clearTimeout(retry);
      esRef.current?.close();
      esRef.current = null;
    };
  }, [runId, appendEvent]);

  // ----------------------------------------------------------------- cancel
  const cancel = async () => {
    if (!runId || cancelling) return;
    setCancelling(true);
    setCancelErr(null);
    try {
      await api.cancelRun(runId);
      const rd = await api.getRun(runId);
      setRun(rd);
    } catch (e) {
      setCancelErr(errMsg(e));
    } finally {
      setCancelling(false);
    }
  };

  // ------------------------------------------------------------- derived
  const runLevelEvents = useMemo(() => events.filter((e) => !e.system), [events]);
  const eventsBySys = useMemo(() => {
    const map = new Map<SystemID, RunEvent[]>();
    for (const e of events) {
      if (!e.system) continue;
      const arr = map.get(e.system);
      if (arr) arr.push(e);
      else map.set(e.system, [e]);
    }
    return map;
  }, [events]);

  const visibleSystems = useMemo(() => {
    if (!run) return [];
    const present = new Set(run.systems.map((s) => s.system));
    return SYSTEM_ORDER.filter((s) => present.has(s));
  }, [run]);

  // ----------------------------------------------------------------- render
  return (
    <div className="exec-view">
      <div className="exec-toolbar">
        <label className="label" htmlFor="run-select">
          Run
        </label>
        <select
          id="run-select"
          className="select"
          value={runId ?? ''}
          onChange={(e) => setRunId(e.target.value || null)}
        >
          <option value="" disabled>
            {runsLoading ? 'Loading runs…' : 'Select a run…'}
          </option>
          {(runs ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {fmtTime(r.created_at)} · {r.repo_name} · {r.status} · {r.task.slice(0, 48)}
            </option>
          ))}
          {runId && run && runs && !runs.some((r) => r.id === runId) && (
            <option value={runId}>{fmtTime(run.created_at)} · {run.repo_name} · {run.status}</option>
          )}
        </select>
        <button type="button" className="btn btn-sm" onClick={() => void loadRuns()}>
          ↻ refresh
        </button>

        {run && (
          <>
            <StatusPill status={run.status} />
            <span className="muted small">
              started {fmtTime(run.created_at)}
              {run.finished_at ? ` · finished ${fmtTime(run.finished_at)}` : ''}
            </span>
            {!isTerminal(run.status) && (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={cancelling}
                onClick={() => void cancel()}
              >
                {cancelling ? 'Cancelling…' : 'Cancel run'}
              </button>
            )}
          </>
        )}
        <span className="exec-stream muted small">
          {run && !isTerminal(run.status) ? '● live (SSE)' : run ? 'stream closed' : ''}
        </span>
      </div>

      {runsErr && <ErrorBanner message={runsErr} onRetry={() => void loadRuns()} />}
      {cancelErr && <ErrorBanner message={`Cancel failed: ${cancelErr}`} />}

      {!runId && (
        <EmptyState
          title="No run selected"
          hint={
            runs && runs.length > 0
              ? 'Choose a run from the selector above to watch it execute.'
              : 'Execute a task from the Workspace tab to create your first run.'
          }
        />
      )}

      {runId && runErr && <ErrorBanner message={runErr} />}

      {runId && !run && !runErr && <Spinner label="Loading run…" />}

      {run && (
        <>
          <div className="run-taskbar">
            <span className="tag mono">{run.repo_name}</span>
            <span className="run-task">{run.task}</span>
          </div>

          {/* run-level (system-less) events */}
          <div className="run-feed-wrap">
            <span className="run-feed-label">run</span>
            <EventFeed events={runLevelEvents} emptyHint="Waiting for run events…" />
          </div>

          {run.systems.length === 0 && (
            <EmptyState title="No systems in this run" hint="The run recorded no per-system execution." />
          )}

          <div className="sys-panels" style={{ '--panel-count': visibleSystems.length } as CSSProperties}>
            {visibleSystems.map((sysId) => {
              const sys = run.systems.find((s) => s.system === sysId);
              if (!sys) return null;
              const meta = SYSTEM_META[sysId];
              const over = live[sysId] ?? {};
              const m: Partial<RunMetrics> = { ...(sys.metrics ?? {}), ...over };
              const finished = isTerminal(sys.status);
              const feed = eventsBySys.get(sysId) ?? [];

              return (
                <section
                  key={sysId}
                  className="sys-panel"
                  style={{ '--accent': meta.color } as CSSProperties}
                >
                  <header className="sys-head">
                    <span className="sys-letter">{sysId}</span>
                    <span className="sys-name">{meta.name}</span>
                    <StatusPill status={sys.status} />
                    <CompletionBadge completion={m.completion ?? null} />
                    <span className="sys-agent muted small">
                      agent: <span className="mono">{sys.current_agent ?? '—'}</span>
                    </span>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setDetailSys(sysId)}
                    >
                      Details
                    </button>
                  </header>

                  {sys.error && <div className="sys-error">{sys.error}</div>}

                  <StageStepper stage={sys.stage} finished={finished} />

                  <div className="metrics-grid">
                    <div className="metric">
                      <span className="metric-value">{fmtNum(m.tokens ?? 0)}</span>
                      <span className="metric-label">tokens</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtCost(m.cost_usd ?? 0)}</span>
                      <span className="metric-label">cost</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtNum(m.tool_calls ?? 0)}</span>
                      <span className="metric-label">tool calls</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtNum(m.files_modified ?? 0)}</span>
                      <span className="metric-label">files mod.</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">
                        <span className="ok-num">{fmtNum(m.tests_passed ?? 0)}</span>
                        <span className="sep">/</span>
                        <span className="bad-num">{fmtNum(m.tests_failed ?? 0)}</span>
                      </span>
                      <span className="metric-label">tests pass/fail</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtNum(m.repairs ?? 0)}</span>
                      <span className="metric-label">repairs</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtNum(m.graph_queries ?? 0)}</span>
                      <span className="metric-label">graph queries</span>
                    </div>
                    <div className="metric">
                      <span className="metric-value">{fmtDuration(m.duration_ms ?? 0)}</span>
                      <span className="metric-label">duration</span>
                    </div>
                  </div>

                  <EventFeed events={feed} emptyHint="Waiting for events…" />
                </section>
              );
            })}
          </div>
        </>
      )}

      {detailSys && runId && (
        <DetailModal runId={runId} system={detailSys} onClose={() => setDetailSys(null)} />
      )}
    </div>
  );
}
