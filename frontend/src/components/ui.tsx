import { useEffect, type ReactNode } from 'react';
import type {
  GraphStatus,
  RunStatus,
  Stage,
  SystemID,
  SysStatus,
} from '../api/types';

// ---------------------------------------------------------------------------
// System metadata (accent colour per system)
// ---------------------------------------------------------------------------

export interface SystemMeta {
  id: SystemID;
  short: string;
  name: string;
  desc: string;
  color: string;
}

export const SYSTEM_META: Record<SystemID, SystemMeta> = {
  A: {
    id: 'A',
    short: 'A',
    name: 'Standard',
    desc: 'Agentic coding loop with file reads, edits and tests — no graph context.',
    color: '#60a5fa',
  },
  B: {
    id: 'B',
    short: 'B',
    name: 'Graph-Augmented',
    desc: 'Same loop, but queries the code knowledge graph for callers / callees context.',
    color: '#34d399',
  },
  C: {
    id: 'C',
    short: 'C',
    name: 'GNN-Enhanced',
    desc: 'Graph context plus learned GNN impact scores to prioritise nodes.',
    color: '#a78bfa',
  },
};

export const SYSTEM_ORDER: SystemID[] = ['A', 'B', 'C'];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '--:--:--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--:--';
  return d.toISOString().slice(11, 19);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  if (m < 60) return `${m}m ${rem}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtNum(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('en-US');
}

export function fmtCost(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  if (v > 0 && v < 0.001) return `<$0.001`;
  return `$${v.toFixed(4)}`;
}

export function fmtBytes(b: number | null | undefined): string {
  if (b == null || Number.isNaN(b)) return '';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="spinner-row" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="muted">{label}</span>
    </div>
  );
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-banner" role="alert">
      <span className="error-icon" aria-hidden="true">
        ⚠
      </span>
      <span className="error-msg">{message}</span>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {hint && <div className="muted">{hint}</div>}
      {action}
    </div>
  );
}

export function Panel({
  title,
  right,
  children,
  className = '',
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <header className="panel-head">
          <h2 className="panel-title">{title}</h2>
          {right && <div className="panel-right">{right}</div>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pills / badges
// ---------------------------------------------------------------------------

type Tone = 'neutral' | 'info' | 'success' | 'warn' | 'danger' | 'running';

export function Pill({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusPill({ status }: { status: RunStatus | SysStatus | string }) {
  const tone: Tone =
    status === 'completed'
      ? 'success'
      : status === 'failed'
        ? 'danger'
        : status === 'cancelled'
          ? 'warn'
          : status === 'running'
            ? 'running'
            : status === 'queued' || status === 'pending'
              ? 'info'
              : 'neutral';
  return <Pill tone={tone}>{status}</Pill>;
}

export function GraphStatusPill({ status }: { status: GraphStatus | string }) {
  const tone: Tone =
    status === 'ready'
      ? 'success'
      : status === 'building'
        ? 'running'
        : status === 'error'
          ? 'danger'
          : 'neutral';
  return <Pill tone={tone}>graph: {status}</Pill>;
}

export function CompletionBadge({ completion }: { completion: string | null | undefined }) {
  if (!completion || completion === 'pending') return null;
  const tone: Tone =
    completion === 'success' ? 'success' : completion === 'partial' ? 'warn' : 'danger';
  return (
    <span className={`pill pill-${tone} completion-badge`}>
      {completion === 'success' ? '✓ ' : '✕ '}
      {completion}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? 'modal-wide' : ''}`}
        role="dialog"
        aria-modal="true"
      >
        <header className="modal-head">
          <div className="modal-title">{title}</div>
          <button
            type="button"
            className="btn btn-sm close-x"
            onClick={onClose}
            aria-label="Close dialog"
          >
            ✕
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage stepper helpers
// ---------------------------------------------------------------------------

export function stageIndex(stage: Stage | null | undefined): number {
  if (!stage) return -1;
  if (stage === 'done') return 99;
  const order: Stage[] = ['explore', 'plan', 'edit', 'test', 'repair'];
  const i = order.indexOf(stage);
  return i;
}

export function StageStepper({
  stage,
  finished,
}: {
  stage: Stage | null | undefined;
  finished: boolean;
}) {
  const order: Stage[] = ['explore', 'plan', 'edit', 'test', 'repair'];
  const cur = stageIndex(stage);
  return (
    <ol className="stepper" aria-label="Execution stages">
      {order.map((s, i) => {
        const done = finished || (cur >= 0 && cur > i && cur !== 99) || cur === 99;
        const active = !finished && cur === i;
        return (
          <li
            key={s}
            className={`step ${done ? 'done' : ''} ${active ? 'active' : ''}`}
            aria-current={active ? 'step' : undefined}
          >
            <span className="step-dot" aria-hidden="true">
              {done ? '✓' : i + 1}
            </span>
            <span className="step-label">{s}</span>
            {i < order.length - 1 && <span className="step-line" aria-hidden="true" />}
          </li>
        );
      })}
      {finished && (
        <li className="step done">
          <span className="step-dot" aria-hidden="true">
            ✓
          </span>
          <span className="step-label">done</span>
        </li>
      )}
    </ol>
  );
}
