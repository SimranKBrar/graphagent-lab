import type {
  BenchmarkResults,
  BenchmarkTask,
  CreateRunInput,
  EventsResponse,
  FileContent,
  GraphData,
  GraphNode,
  GraphNodeDetail,
  GraphStatusResponse,
  Health,
  RepoDetail,
  RepoSummary,
  RunDetail,
  RunSummary,
  SystemDetail,
} from './types';

const BASE = '/api';

/** Error carrying the HTTP status plus the backend's `detail` message. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError('Backend unreachable — is the API server running?', 0);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status} ${res.statusText})`;
    try {
      const body = (await res.json()) as { detail?: unknown } | null;
      if (body && body.detail !== undefined && body.detail !== null) {
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      /* body was not JSON — keep the status text */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  };
}

export const api = {
  // Health -----------------------------------------------------------------
  health: () => request<Health>('/health'),

  // Repositories -------------------------------------------------------------
  listRepos: () => request<RepoSummary[]>('/repos'),

  uploadRepo: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<RepoDetail>('/repos/upload', { method: 'POST', body: fd });
  },

  addGithubRepo: (url: string, branch?: string) =>
    request<RepoDetail>(
      '/repos/github',
      jsonBody({ url, branch: branch && branch.trim() ? branch.trim() : null }),
    ),

  getRepo: (id: string) => request<RepoDetail>(`/repos/${encodeURIComponent(id)}`),

  getRepoFile: (id: string, path: string) =>
    request<FileContent>(
      `/repos/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`,
    ),

  deleteRepo: (id: string) =>
    request<{ ok: boolean }>(`/repos/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  // Code knowledge graph -----------------------------------------------------
  getGraph: (repoId: string) =>
    request<GraphStatusResponse>(`/repos/${encodeURIComponent(repoId)}/graph`),

  buildGraph: (repoId: string) =>
    request<{ status: string }>(`/repos/${encodeURIComponent(repoId)}/graph`, {
      method: 'POST',
    }),

  getGraphData: (repoId: string) =>
    request<GraphData>(`/repos/${encodeURIComponent(repoId)}/graph/data`),

  searchGraph: (repoId: string, q: string) =>
    request<GraphNode[]>(
      `/repos/${encodeURIComponent(repoId)}/graph/search?q=${encodeURIComponent(q)}`,
    ),

  getGraphNode: (repoId: string, nodeId: string) =>
    request<GraphNodeDetail>(
      `/repos/${encodeURIComponent(repoId)}/graph/node?node_id=${encodeURIComponent(nodeId)}`,
    ),

  getGraphSubgraph: (repoId: string, center: string, depth = 2) =>
    request<GraphData>(
      `/repos/${encodeURIComponent(repoId)}/graph/subgraph?center=${encodeURIComponent(center)}&depth=${depth}`,
    ),

  // Runs --------------------------------------------------------------------
  createRun: (input: CreateRunInput) =>
    request<RunDetail>('/runs', jsonBody(input)),

  listRuns: () => request<RunSummary[]>('/runs'),

  getRun: (id: string) => request<RunDetail>(`/runs/${encodeURIComponent(id)}`),

  cancelRun: (id: string) =>
    request<{ ok: boolean }>(`/runs/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    }),

  getRunEvents: (id: string, after = 0, limit = 500) =>
    request<EventsResponse>(
      `/runs/${encodeURIComponent(id)}/events?after=${after}&format=json&limit=${limit}`,
    ),

  getSystemDetail: (runId: string, system: string) =>
    request<SystemDetail>(
      `/runs/${encodeURIComponent(runId)}/system/${encodeURIComponent(system)}`,
    ),

  // SSE endpoint (EventSource cannot set headers — `after` goes in the query).
  runEventsSseUrl: (id: string, after: number) =>
    `${BASE}/runs/${encodeURIComponent(id)}/events?after=${after}`,

  // Benchmark ---------------------------------------------------------------
  benchmarkTasks: () => request<BenchmarkTask[]>('/benchmark/tasks'),

  benchmarkResults: () => request<BenchmarkResults>('/benchmark/results'),
};

export type Api = typeof api;
