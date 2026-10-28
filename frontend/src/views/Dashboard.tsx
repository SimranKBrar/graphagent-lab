import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api, ApiError } from '../api/client';
import type { BenchmarkResults, BenchmarkTask, SystemAggregate, SystemID } from '../api/types';
import {
  EmptyState,
  ErrorBanner,
  Spinner,
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

type Better = 'high' | 'low' | 'none';

interface Col {
  key: keyof SystemAggregate;
  label: string;
  better: Better;
  fmt: (v: number) => string;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const one = (v: number) => v.toFixed(1);

const COLS: Col[] = [
  { key: 'completion_rate', label: 'Completion rate', better: 'high', fmt: pct },
  { key: 'avg_tests_passed', label: 'Avg tests passed', better: 'high', fmt: one },
  { key: 'avg_tokens', label: 'Avg tokens', better: 'low', fmt: (v) => fmtNum(Math.round(v)) },
  { key: 'avg_cost_usd', label: 'Avg cost', better: 'low', fmt: (v) => fmtCost(v) },
  { key: 'avg_duration_ms', label: 'Avg duration', better: 'low', fmt: (v) => fmtDuration(v) },
  { key: 'avg_tool_calls', label: 'Avg tool calls', better: 'low', fmt: one },
  { key: 'avg_repairs', label: 'Avg repairs', better: 'low', fmt: one },
  { key: 'avg_files_modified', label: 'Avg files modified', better: 'none', fmt: one },
  { key: 'avg_graph_queries', label: 'Avg graph queries', better: 'none', fmt: one },
];

interface ChartDef {
  key: keyof SystemAggregate;
  label: string;
  fmt: (v: number) => string;
}

const CHARTS: ChartDef[] = [
  { key: 'avg_tokens', label: 'Avg tokens', fmt: (v) => fmtNum(Math.round(v)) },
  { key: 'avg_duration_ms', label: 'Avg duration', fmt: (v) => fmtDuration(v) },
  { key: 'avg_tool_calls', label: 'Avg tool calls', fmt: one },
  { key: 'avg_tests_passed', label: 'Avg tests passed', fmt: one },
  { key: 'avg_cost_usd', label: 'Avg cost (USD)', fmt: (v) => fmtCost(v) },
];

interface RadarDef {
  key: keyof SystemAggregate;
  label: string;
  better: 'high' | 'low';
}

const RADAR: RadarDef[] = [
  { key: 'completion_rate', label: 'Completion', better: 'high' },
  { key: 'avg_tests_passed', label: 'Tests', better: 'high' },
  { key: 'avg_tokens', label: 'Token eff.', better: 'low' },
  { key: 'avg_cost_usd', label: 'Cost eff.', better: 'low' },
  { key: 'avg_duration_ms', label: 'Speed', better: 'low' },
  { key: 'avg_tool_calls', label: 'Tool eff.', better: 'low' },
  { key: 'avg_repairs', label: 'Repair eff.', better: 'low' },
];

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

// ---------------------------------------------------------------------------
// Grouped metric chart (one system per bar, coloured A/B/C)
// ---------------------------------------------------------------------------

function MetricChart({
  title,
  rows,
  fmt,
}: {
  title: string;
  rows: { name: string; v: number; fill: string }[];
  fmt: (v: number) => string;
}) {
  return (
    <div className="chart-card">
      <div className="chart-title">{title}</div>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
            <XAxis dataKey="name" stroke="#6b7280" fontSize={11} tickLine={false} axisLine={{ stroke: '#1f2937' }} />
            <YAxis stroke="#6b7280" fontSize={10} tickLine={false} width={48} axisLine={false} />
            <Tooltip
              contentStyle={{
                background: '#111827',
                border: '1px solid #1f2937',
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: '#e5e7eb' }}
              cursor={{ fill: 'rgba(96,165,250,0.06)' }}
              formatter={(v: unknown) => fmt(Number(v))}
            />
            <Bar dataKey="v" radius={[4, 4, 0, 0]} maxBarSize={56}>
              {rows.map((r) => (
                <Cell key={r.name} fill={r.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [results, setResults] = useState<BenchmarkResults | null>(null);
  const [resErr, setResErr] = useState<string | null>(null);
  const [resLoading, setResLoading] = useState(true);
  const [resTick, setResTick] = useState(0);

  const [tasks, setTasks] = useState<BenchmarkTask[] | null>(null);
  const [tasksErr, setTasksErr] = useState<string | null>(null);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksTick, setTasksTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setResLoading(true);
    setResErr(null);
    api
      .benchmarkResults()
      .then((r) => {
        if (!cancelled) setResults(r);
      })
      .catch((e) => {
        if (!cancelled) setResErr(errMsg(e));
      })
      .finally(() => {
        if (!cancelled) setResLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resTick]);

  useEffect(() => {
    let cancelled = false;
    setTasksLoading(true);
    setTasksErr(null);
    api
      .benchmarkTasks()
      .then((t) => {
        if (!cancelled) setTasks(t);
      })
      .catch((e) => {
        if (!cancelled) setTasksErr(errMsg(e));
      })
      .finally(() => {
        if (!cancelled) setTasksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tasksTick]);

  const reload = useCallback(() => {
    setResTick((t) => t + 1);
    setTasksTick((t) => t + 1);
  }, []);

  // Which systems actually have aggregates this run ------------------------
  const present = useMemo(() => {
    const map = new Map<SystemID, SystemAggregate>();
    for (const s of SYSTEM_ORDER) {
      const a = results?.aggregates?.[s];
      if (a) map.set(s, a);
    }
    return map;
  }, [results]);

  // Best-value highlighting -------------------------------------------------
  const bestValues = useMemo(() => {
    const out = new Map<string, Set<SystemID>>();
    for (const col of COLS) {
      if (col.better === 'none') continue;
      const values: { sys: SystemID; v: number }[] = [];
      for (const s of SYSTEM_ORDER) {
        const a = present.get(s);
        if (!a) continue;
        const v = num(a[col.key]);
        if (v != null) values.push({ sys: s, v });
      }
      if (values.length < 2 || new Set(values.map((x) => x.v)).size < 2) continue;
      const target =
        col.better === 'high'
          ? Math.max(...values.map((x) => x.v))
          : Math.min(...values.map((x) => x.v));
      const winners = new Set(values.filter((x) => x.v === target).map((x) => x.sys));
      out.set(col.key, winners);
    }
    return out;
  }, [present]);

  const chartRows = useMemo(() => {
    return CHARTS.map((c) => ({
      def: c,
      rows: SYSTEM_ORDER.filter((s) => present.has(s)).map((s) => {
        const a = present.get(s)!;
        return {
          name: s,
          v: num(a[c.key]) ?? 0,
          fill: SYSTEM_META[s].color,
        };
      }),
    }));
  }, [present]);

  const radarData = useMemo(() => {
    return RADAR.map((m) => {
      const row: Record<string, string | number> = { metric: m.label };
      const nums: number[] = [];
      for (const s of SYSTEM_ORDER) {
        const v = present.get(s) ? num(present.get(s)![m.key]) : null;
        if (v != null) nums.push(v);
      }
      const min = nums.length ? Math.min(...nums) : 0;
      const max = nums.length ? Math.max(...nums) : 0;
      for (const s of SYSTEM_ORDER) {
        const a = present.get(s);
        if (!a) continue;
        const v = num(a[m.key]);
        if (v == null) continue;
        let norm = 0.5;
        if (max !== min) {
          norm = m.better === 'high' ? (v - min) / (max - min) : (max - v) / (max - min);
        }
        row[s] = Math.round(norm * 100) / 100;
      }
      return row;
    });
  }, [present]);

  const runs = results?.runs ?? [];
  const hasAggregates = present.size > 0;
  const showEmpty = !resLoading && !resErr && runs.length === 0;

  return (
    <div className="dash-view">
      <div className="dash-head">
        <h1 className="view-title">Benchmark</h1>
        <button type="button" className="btn btn-sm" onClick={reload}>
          ↻ refresh
        </button>
      </div>

      {resErr && <ErrorBanner message={resErr} onRetry={() => setResTick((t) => t + 1)} />}
      {resLoading && <Spinner label="Loading benchmark results…" />}

      {showEmpty && (
        <EmptyState
          title="No runs yet — execute a task from the Workspace tab"
          hint="Aggregated metrics, charts and per-run breakdowns will appear once runs complete."
        />
      )}

      {!resLoading && !resErr && !showEmpty && (
        <>
          {/* ---------------------------------------------------- comparison */}
          {hasAggregates ? (
            <section className="panel">
              <header className="panel-head">
                <h2 className="panel-title">System comparison</h2>
                <div className="panel-right muted small">best value highlighted</div>
              </header>
              <div className="panel-body">
                <div className="table-scroll">
                  <table className="table compare-table">
                    <thead>
                      <tr>
                        <th>System</th>
                        {COLS.map((c) => (
                          <th key={c.key}>{c.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {SYSTEM_ORDER.filter((s) => present.has(s)).map((s) => {
                        const a = present.get(s)!;
                        return (
                          <tr key={s}>
                            <th scope="row">
                              <span className="sys-cell" style={{ color: SYSTEM_META[s].color }}>
                                <span className="sys-cell-letter">{s}</span>
                                <span className="sys-cell-name">{SYSTEM_META[s].name}</span>
                              </span>
                              <span className="muted small">{a.runs} runs</span>
                            </th>
                            {COLS.map((c) => {
                              const v = num(a[c.key]);
                              const best = bestValues.get(c.key)?.has(s) ?? false;
                              return (
                                <td key={c.key} className={`mono ${best ? 'best' : ''}`}>
                                  {v == null ? '—' : c.fmt(v)}
                                  {best && (
                                    <span className="best-star" title="best value">
                                      ★
                                    </span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          ) : (
            <EmptyState title="No aggregates yet" hint="Complete a run to populate benchmark statistics." />
          )}

          {/* -------------------------------------------------------- charts */}
          <section className="panel">
            <header className="panel-head">
              <h2 className="panel-title">Metrics</h2>
              <div className="panel-right muted small">A blue · B green · C purple</div>
            </header>
            <div className="panel-body">
              <div className="charts-grid">
                {chartRows.map(({ def, rows }) => (
                  <MetricChart key={def.key} title={def.label} rows={rows} fmt={def.fmt} />
                ))}
              </div>
            </div>
          </section>

          {/* --------------------------------------------------------- radar */}
          {hasAggregates && (
            <section className="panel">
              <header className="panel-head">
                <h2 className="panel-title">Normalised profile</h2>
                <div className="panel-right muted small">min–max across systems · higher = better</div>
              </header>
              <div className="panel-body">
                <div className="radar-box">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData} outerRadius="68%">
                      <PolarGrid stroke="#1f2937" />
                      <PolarAngleAxis
                        dataKey="metric"
                        tick={{ fill: '#9ca3af', fontSize: 10 }}
                      />
                      <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
                      <Tooltip
                        contentStyle={{
                          background: '#111827',
                          border: '1px solid #1f2937',
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      {SYSTEM_ORDER.filter((s) => present.has(s)).map((s) => (
                        <Radar
                          key={s}
                          name={`${s} · ${SYSTEM_META[s].name}`}
                          dataKey={s}
                          stroke={SYSTEM_META[s].color}
                          fill={SYSTEM_META[s].color}
                          fillOpacity={0.14}
                        />
                      ))}
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </section>
          )}

          {/* --------------------------------------------------- per-run table */}
          <section className="panel">
            <header className="panel-head">
              <h2 className="panel-title">Per-run breakdown</h2>
              <div className="panel-right muted small">{runs.length} runs</div>
            </header>
            <div className="panel-body">
              <div className="table-scroll">
                <table className="table runs-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Task</th>
                      <th>Started</th>
                      {SYSTEM_ORDER.map((s) => (
                        <th key={s} style={{ color: SYSTEM_META[s].color }}>
                          {s}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.run_id}>
                        <td className="mono small">{r.run_id}</td>
                        <td className="task-cell" title={r.task}>
                          {r.task}
                        </td>
                        <td className="mono small">{fmtTime(r.created_at)}</td>
                        {SYSTEM_ORDER.map((s) => {
                          const m = r.systems?.[s];
                          if (!m) return <td key={s} className="muted">—</td>;
                          const comp = m.completion;
                          const compCls =
                            comp === 'success'
                              ? 'ok-num'
                              : comp === 'partial'
                                ? 'warn-num'
                                : comp === 'failed'
                                  ? 'bad-num'
                                  : 'muted';
                          return (
                            <td key={s}>
                              {/* flex must live on a div, not the td — display:flex
                                  on a td breaks table-cell layout and stacks the
                                  three system columns on top of each other */}
                              <div className="run-sys">
                                <span className={`mono small ${compCls}`}>{comp ?? 'pending'}</span>
                                <span className="muted small">
                                  {num(m.tests_passed) ?? 0}✓/{num(m.tests_failed) ?? 0}✗ ·{' '}
                                  {fmtNum(num(m.tokens) ?? 0)} tok
                                </span>
                                <span className="muted small">
                                  {fmtCost(num(m.cost_usd) ?? 0)} · {fmtDuration(num(m.duration_ms) ?? 0)}
                                </span>
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}

      {/* ------------------------------------------------------------ tasks */}
      <section className="panel">
        <header className="panel-head">
          <h2 className="panel-title">Benchmark tasks</h2>
        </header>
        <div className="panel-body">
          {tasksLoading && <Spinner label="Loading tasks…" />}
          {tasksErr && <ErrorBanner message={tasksErr} onRetry={() => setTasksTick((t) => t + 1)} />}
          {!tasksLoading && !tasksErr && tasks && tasks.length === 0 && (
            <EmptyState title="No benchmark tasks loaded" hint="The task suite is empty." />
          )}
          {!tasksLoading && !tasksErr && tasks && tasks.length > 0 && (
            <div className="task-cards">
              {tasks.map((t) => (
                <article key={t.id} className="task-card">
                  <header className="task-card-head">
                    <span className="task-title">{t.title}</span>
                    {t.hidden_tests && (
                      <span className="pill pill-warn" title="Hidden tests are not shown to the agent">
                        hidden tests
                      </span>
                    )}
                  </header>
                  <div className="chip-row">
                    <span className="tag">{t.category}</span>
                    <span className={`tag diff-${t.difficulty}`}>{t.difficulty}</span>
                    <span className="tag mono">{t.repo}</span>
                  </div>
                  <p className="task-desc muted small">{t.description}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
