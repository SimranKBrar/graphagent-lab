import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from './api/client';
import type { Health } from './api/types';
import Workspace from './views/Workspace';
import Execution from './views/Execution';
import GraphExplorer from './views/GraphExplorer';
import Dashboard from './views/Dashboard';

type TabId = 'workspace' | 'execution' | 'graph' | 'dashboard';

const TABS: { id: TabId; label: string }[] = [
  { id: 'workspace', label: 'Repository Workspace' },
  { id: 'execution', label: 'Live Execution' },
  { id: 'graph', label: 'Graph Explorer' },
  { id: 'dashboard', label: 'Benchmark' },
];

function HealthChip() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  const load = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth(h);
      setOffline(false);
    } catch (e) {
      setHealth(null);
      setOffline(e instanceof ApiError || e instanceof Error);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = window.setInterval(load, 20000);
    return () => window.clearInterval(iv);
  }, [load]);

  if (offline) {
    return (
      <span className="health-chip offline" title="Cannot reach GET /api/health">
        <span className="dot" aria-hidden="true" />
        backend offline
      </span>
    );
  }
  if (!health) {
    return (
      <span className="health-chip" title="Checking backend health…">
        <span className="spinner spinner-sm" aria-hidden="true" />
        checking…
      </span>
    );
  }
  return (
    <span
      className="health-chip online"
      title={`${health.status} · version ${health.version} · docker_available=${health.docker_available}`}
    >
      <span className="dot" aria-hidden="true" />
      <span className="mono">{health.model}</span>
      <span className="sep">·</span>
      <span className={`llm-mode llm-${health.llm_mode}`}>{health.llm_mode}</span>
      <span className="sep">·</span>
      <span>{health.isolation}</span>
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState<TabId>('workspace');
  // Run selected for the Live Execution view (set when a run is created).
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const handleRunCreated = useCallback((runId: string) => {
    setActiveRunId(runId);
    setTab('execution');
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ⬡
          </span>
          <div className="brand-text">
            <span className="brand-title">GraphAgent Lab</span>
            <span className="brand-sub">
              multi-agent coding benchmark · standard vs graph-augmented vs GNN-enhanced
            </span>
          </div>
        </div>

        <nav className="tabs" aria-label="Views">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`tab ${tab === t.id ? 'active' : ''}`}
              aria-current={tab === t.id ? 'page' : undefined}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="topbar-right">
          <HealthChip />
        </div>
      </header>

      <main className="main">
        {tab === 'workspace' && <Workspace onRunCreated={handleRunCreated} />}
        {tab === 'execution' && (
          <Execution runId={activeRunId} setRunId={setActiveRunId} />
        )}
        {tab === 'graph' && <GraphExplorer />}
        {tab === 'dashboard' && <Dashboard />}
      </main>
    </div>
  );
}
