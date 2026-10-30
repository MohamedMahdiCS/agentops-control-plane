import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  Activity,
  Bot,
  ClipboardCheck,
  KeyRound,
  Radio,
  ShieldCheck,
  ShieldAlert,
} from 'lucide-react'
import { ApiError, getControlPlaneOverview, type Agent, type ControlPlaneOverview } from '../../api'
import { useOperator } from '../../operator-context'

const POLL_MS = 10_000

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(1, ...values)
  const step = 100 / Math.max(values.length - 1, 1)
  const points = values.map((v, i) => `${(i * step).toFixed(2)},${(30 - (v / max) * 26).toFixed(2)}`)
  return (
    <svg className="ng-spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={`0,32 ${points.join(' ')} 100,32`} fill={color} fillOpacity="0.12" stroke="none" />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function Kpi({
  label,
  icon,
  accent,
  value,
  foot,
  children,
}: {
  label: string
  icon: ReactNode
  accent: string
  value: ReactNode
  foot: string
  children?: ReactNode
}) {
  return (
    <div className="ng-kpi" style={{ ['--ng-accent' as string]: accent }}>
      <span className="ng-kpi-label">
        {icon}
        {label}
      </span>
      <span className="ng-kpi-value">{value}</span>
      {children}
      <span className="ng-kpi-foot">{foot}</span>
    </div>
  )
}

const EVENT_TONE: Record<string, string> = {
  'tool.authorization': '#7c6cff',
  'tool.outcome': '#5ee7ff',
  'tool.approval_requested': '#ffb547',
  'approval.decided': '#ffb547',
  'approval.expired': '#ff6b81',
  'evaluation.recorded': '#b6a8ff',
}

function describeEvent(type: string): string {
  const labels: Record<string, string> = {
    'tool.authorization': 'Tool request authorized',
    'tool.outcome': 'Tool outcome recorded',
    'tool.approval_requested': 'Human approval requested',
    'approval.decided': 'Approval decided',
    'approval.expired': 'Approval expired',
    'evaluation.recorded': 'Evaluation recorded',
  }
  return labels[type] ?? type
}

function relativeTime(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86_400)}d ago`
}

function useOverview(token: string) {
  const [data, setData] = useState<ControlPlaneOverview | null>(null)
  const [error, setError] = useState('')
  const failures = useRef(0)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()

    async function load() {
      try {
        const result = await getControlPlaneOverview(token, controller.signal)
        if (cancelled) return
        failures.current = 0
        setData(result)
        setError('')
      } catch (cause) {
        if (cancelled) return
        failures.current += 1
        setError(
          cause instanceof ApiError && cause.status === 401
            ? 'The operator token was rejected.'
            : 'Live telemetry is unavailable right now.',
        )
      }
      if (!cancelled && failures.current < 3 && document.visibilityState !== 'hidden') {
        timer = setTimeout(() => void load(), POLL_MS)
      }
    }

    timer = setTimeout(() => void load(), 0)
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [token])

  return { data: token ? data : null, error: token ? error : '' }
}

const OverviewData = createContext<{ data: ControlPlaneOverview | null; error: string }>({ data: null, error: '' })

/** Polls the overview once for every live panel on the page. */
export function OverviewDataProvider({ children }: { children: ReactNode }) {
  const { token } = useOperator()
  const value = useOverview(token)
  return <OverviewData.Provider value={value}>{children}</OverviewData.Provider>
}

export function OverviewKpis({ agents, loading }: { agents: Agent[]; loading: boolean }) {
  const { token } = useOperator()
  const { data } = useContext(OverviewData)
  const active = agents.filter((agent) => agent.status === 'active').length
  const locked = !token
  const passRate = data?.evaluations.pass_rate
  const gate = data?.latest_benchmark?.gate

  return (
    <section className="ng-kpis" aria-label="Control plane status">
      <Kpi
        label="Registered agents"
        icon={<Bot size={15} />}
        accent="#7c6cff"
        value={loading ? '—' : agents.length}
        foot={`${active} active`}
      />
      <Kpi
        label="Runs, last 24h"
        icon={<Activity size={15} />}
        accent="#5ee7ff"
        value={locked ? '—' : (data?.runs.last_24h ?? '…')}
        foot={locked ? 'Unlock operator mode for telemetry' : `${data?.runs.total ?? 0} runs recorded in total`}
      >
        {data && <Sparkline values={data.runs.hourly} color="#5ee7ff" />}
      </Kpi>
      <Kpi
        label="Evaluation pass rate"
        icon={<ClipboardCheck size={15} />}
        accent="#4be3c0"
        value={locked ? '—' : passRate === null || passRate === undefined ? 'n/a' : `${Math.round(passRate * 100)}%`}
        foot={locked ? 'Evidence-linked grading' : `${data?.evaluations.total ?? 0} evaluations, inconclusive counted as not passed`}
      >
        {data && passRate !== null && passRate !== undefined && (
          <div className="ng-meter" aria-hidden="true">
            <span style={{ width: `${Math.round(passRate * 100)}%` }} />
          </div>
        )}
      </Kpi>
      <Kpi
        label="Release gate"
        icon={gate === 'failed' ? <ShieldAlert size={15} /> : <ShieldCheck size={15} />}
        accent={gate === 'failed' ? '#ff6b81' : gate === 'blocked' ? '#ffb547' : '#b6a8ff'}
        value={locked ? '—' : gate ? gate.replace('_', ' ').replace(/^./, (c) => c.toUpperCase()) : 'Not run'}
        foot={
          locked
            ? 'Latest benchmark decision'
            : data?.latest_benchmark
              ? data.latest_benchmark.label
              : 'Run a benchmark to compute release gates'
        }
      />
    </section>
  )
}

export function LiveEventStream() {
  const { token, setToken } = useOperator()
  const { data, error } = useContext(OverviewData)
  const [draft, setDraft] = useState('')
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15_000)
    return () => clearInterval(timer)
  }, [])

  function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const value = draft.trim()
    if (value) {
      setToken(value)
      setDraft('')
    }
  }

  if (!token) {
    return (
      <section className="ng-unlock" aria-label="Unlock operator mode">
        <div className="ng-stream-head">
          <h2>Live governance stream</h2>
          <KeyRound size={16} aria-hidden="true" />
        </div>
        <p>
          Tool authorizations, approvals and evaluations stream here in real time. Unlock
          operator mode once and it applies to every view. The token stays in memory only.
        </p>
        <form onSubmit={unlock}>
          <label className="sr-only" htmlFor="overview-operator-token">
            Operator access token
          </label>
          <input
            id="overview-operator-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="Operator token"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" className="button-primary" disabled={!draft.trim()}>
            Unlock
          </button>
        </form>
      </section>
    )
  }

  const events = data?.recent_events ?? []

  return (
    <section className="ng-stream" aria-label="Live governance stream">
      <div className="ng-stream-head">
        <h2>Live governance stream</h2>
        <span className="ng-live">
          <Radio size={13} aria-hidden="true" /> LIVE
        </span>
      </div>
      {error && (
        <p className="ng-empty-stream" role="alert">
          {error}
        </p>
      )}
      {!error && events.length === 0 && (
        <div className="ng-empty-stream">
          <Activity size={20} aria-hidden="true" />
          {data ? 'No governance events recorded yet. Start an investigation to see activity.' : 'Connecting…'}
        </div>
      )}
      <ul className="ng-events" aria-live="polite">
        {events.map((event) => (
          <li key={event.id} className="ng-event" style={{ ['--ng-tone' as string]: EVENT_TONE[event.event_type] ?? '#5ee7ff' }}>
            <span className="ng-event-dot" aria-hidden="true" />
            <span>
              <strong>{describeEvent(event.event_type)}</strong>
              <small>
                {event.actor_type}
                {event.run_id ? ` · run ${event.run_id.slice(0, 8)}` : ''}
              </small>
            </span>
            <time dateTime={event.created_at}>{relativeTime(event.created_at, now)}</time>
          </li>
        ))}
      </ul>
    </section>
  )
}
