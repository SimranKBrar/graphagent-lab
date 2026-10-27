// TypeScript mirrors of docs/API.md (v1). Keep in sync with the contract.

// ---------------------------------------------------------------------------
// Core enums
// ---------------------------------------------------------------------------

export type SystemID = 'A' | 'B' | 'C';
export type Stage = 'explore' | 'plan' | 'edit' | 'test' | 'repair' | 'done';
export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type SysStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type GraphStatus = 'absent' | 'building' | 'ready' | 'error';
export type Completion = 'pending' | 'success' | 'partial' | 'failed';

export const SYSTEM_IDS: SystemID[] = ['A', 'B', 'C'];
export const STAGES: Stage[] = ['explore', 'plan', 'edit', 'test', 'repair'];

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface Health {
  status: string;
  version: string;
  llm_mode: 'mock' | 'openai';
  model: string;
  isolation: 'docker' | 'local';
  docker_available: boolean;
}

// ---------------------------------------------------------------------------
// Repositories
// ---------------------------------------------------------------------------

export interface RepoSummary {
  id: string;
  name: string;
  source_type: 'zip' | 'github';
  origin_url: string | null;
  created_at: string;
  default_branch: string | null;
  file_count: number;
  languages: Record<string, number>;
  graph_status: GraphStatus;
}

export interface TreeNode {
  name: string;
  path: string;
  type: 'dir' | 'file';
  bytes?: number | null;
  children?: TreeNode[] | null;
}

export interface RepoDetail {
  id: string;
  name: string;
  source_type: 'zip' | 'github';
  origin_url: string | null;
  created_at: string;
  default_branch: string | null;
  commit: string | null;
  file_count: number;
  total_bytes: number;
  languages: Record<string, number>;
  graph_status: GraphStatus;
  tree: TreeNode;
}

export interface FileContent {
  path: string;
  content: string;
  truncated: boolean;
}

// ---------------------------------------------------------------------------
// Code knowledge graph
// ---------------------------------------------------------------------------

export interface GraphStats {
  nodes: number;
  edges: number;
  by_kind: Record<string, number>;
  by_edge: Record<string, number>;
  built_at: string | null;
}

export interface GraphStatusResponse {
  status: GraphStatus;
  stats: GraphStats | null;
  error: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  file: string | null;
  line: number | null;
  test: boolean | null;
  loc: number | null;
  gnn_score: number | null;
  gnn_impact: number | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNodeRef {
  id: string;
  label: string;
}

export interface GraphRelatedRef extends GraphNodeRef {
  type?: string;
}

export interface GraphNodeDetail {
  node: GraphNode;
  source: string | null;
  callers: GraphNodeRef[];
  callees: GraphNodeRef[];
  related: GraphRelatedRef[];
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface RunSettings {
  max_iterations: number;
  tool_call_budget: number;
  token_budget: number;
  timeout_sec: number;
  model: string | null;
}

export interface RunSettingsInput {
  max_iterations?: number;
  tool_call_budget?: number;
  token_budget?: number;
  timeout_sec?: number;
  model?: string | null;
}

export interface RunMetrics {
  tool_calls: number;
  llm_calls: number;
  tokens: number;
  cost_usd: number;
  files_inspected: number;
  files_modified: number;
  graph_queries: number;
  tests_passed: number;
  tests_failed: number;
  repairs: number;
  duration_ms: number;
  completion: Completion;
}

export interface PlanStep {
  id: string | number;
  description: string;
  files?: string[];
  symbols?: string[];
}

export interface TestFailure {
  name: string;
  error: string;
  file?: string;
  line?: number | null;
}

export interface TestReport {
  passed: number;
  failed: number;
  failures: TestFailure[];
}

export interface ExploreReport {
  findings: { file: string; note: string }[];
  symbols?: string[];
  files_inspected?: string[];
}

export interface SystemRun {
  system: SystemID;
  status: SysStatus;
  stage: Stage | null;
  current_agent: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  metrics: RunMetrics | null;
  plan: PlanStep[] | null;
  test_report: TestReport | null;
}

export interface RunSummary {
  id: string;
  repo_id: string;
  repo_name: string;
  task: string;
  systems: SystemID[];
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
}

// RunDetail shares RunSummary's fields except `systems`, which is expanded
// from SystemID[] into SystemRun[] (Omit keeps both shapes contract-accurate).
export interface RunDetail extends Omit<RunSummary, 'systems'> {
  settings: RunSettings;
  systems: SystemRun[];
}

export interface CreateRunInput {
  repo_id: string;
  task: string;
  systems: SystemID[];
  settings?: RunSettingsInput;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

export interface RunEvent {
  seq: number;
  ts: string;
  system: SystemID | null;
  type: string;
  stage: Stage | null;
  agent: string | null;
  payload: Record<string, any>;
}

export interface EventsResponse {
  events: RunEvent[];
  next_after: number;
}

export interface EditRecord {
  path: string;
  action: 'create' | 'modify' | 'delete';
  diff: string | null;
  additions: number;
  deletions: number;
}

export interface Repair {
  diagnosis: string;
  root_cause: string;
  target_stage: string;
}

export interface SystemDetail {
  system: SystemID;
  status: SysStatus;
  stage: Stage | null;
  metrics: RunMetrics | null;
  explore_report: ExploreReport | null;
  plan: PlanStep[] | null;
  edits: EditRecord[];
  test_report: TestReport | null;
  repairs: Repair[];
  workspace: string | null;
}

// ---------------------------------------------------------------------------
// Benchmark
// ---------------------------------------------------------------------------

export interface BenchmarkTask {
  id: string;
  title: string;
  category: string;
  repo: string;
  difficulty: string;
  description: string;
  hidden_tests: boolean;
}

export interface SystemAggregate {
  runs: number;
  completion_rate: number;
  avg_tests_passed: number;
  avg_tokens: number;
  avg_cost_usd: number;
  avg_duration_ms: number;
  avg_tool_calls: number;
  avg_repairs: number;
  avg_files_modified: number;
  avg_graph_queries: number;
}

export interface BenchmarkRunSystem extends Partial<RunMetrics> {
  completion?: Completion;
}

export interface BenchmarkRun {
  run_id: string;
  task: string;
  created_at: string;
  systems: Partial<Record<SystemID, BenchmarkRunSystem>>;
}

export interface BenchmarkResults {
  aggregates: Partial<Record<SystemID, SystemAggregate>>;
  runs: BenchmarkRun[];
}
