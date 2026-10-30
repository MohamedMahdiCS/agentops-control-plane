import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  Activity,
  Clock3,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import {
  getRunTraces,
  type RunAuditEvent,
  type RunTraceResponse,
  type RunTraceSpan,
} from '../api'
import { useOperator } from '../operator-context'

interface TraceExplorerProps {
  runId: string
}

type TimelineItem =
  | {
      kind: 'span'
      key: string
      at: string
      span: RunTraceSpan
    }
  | {
      kind: 'audit'
      key: string
      at: string
      event: RunAuditEvent
    }

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : date.toLocaleString()
}

function formatDuration(duration: number | null): string {
  return duration === null ? 'Not recorded' : `${duration.toLocaleString()} ms`
}

export default function TraceExplorer({ runId }: TraceExplorerProps) {
  const { token, setToken, lock: lockSession } = useOperator()
  const [data, setData] = useState<RunTraceResponse | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => controllerRef.current?.abort()
  }, [])

  // Reuse an operator session unlocked elsewhere in the console.
  useEffect(() => {
    if (!token) return
    const timer = setTimeout(() => void loadTraces(), 0)
    return () => clearTimeout(timer)
    // Runs once on mount; later token edits wait for an explicit unlock.
  }, []) // oxlint-disable-line react-hooks/exhaustive-deps

  const timeline = useMemo(() => {
    if (!data) return []

    const items: TimelineItem[] = [
      ...data.spans.map((span) => ({
        kind: 'span' as const,
        key: `span:${span.id}`,
        at: span.started_at,
        span,
      })),
      ...data.audit_events.map((event) => ({
        kind: 'audit' as const,
        key: `audit:${event.id}`,
        at: event.created_at,
        event,
      })),
    ]

    return items.sort(
      (a, b) => a.at.localeCompare(b.at) || a.key.localeCompare(b.key),
    )
  }, [data])

  const selected =
    timeline.find((item) => item.key === selectedKey) ??
    timeline[0] ??
    null

  async function loadTraces(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (!token || loading) return

    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    setLoading(true)
    setError('')

    try {
      const result = await getRunTraces(runId, token, controller.signal)
      if (controller.signal.aborted) return
      setData(result)
      setSelectedKey(null)
    } catch (cause) {
      if (controller.signal.aborted) return
      setData(null)
      setSelectedKey(null)
      setError(
        cause instanceof Error
          ? cause.message
          : 'Unable to retrieve authenticated trace data.',
      )
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  function lockExplorer() {
    controllerRef.current?.abort()
    controllerRef.current = null
    lockSession()
    setData(null)
    setSelectedKey(null)
    setError('')
    setLoading(false)
  }

  return (
    <section className="panel trace-explorer" aria-label="Execution Trace Explorer">
      <div className="panel-heading">
        <div>
          <h2>Execution Trace Explorer</h2>
          <p>Inspect persisted tool activity and governance events.</p>
        </div>
        <span className="count-tag">
          <ShieldCheck size={13} /> OPERATOR ACCESS
        </span>
      </div>

      <div className="trace-access">
        <div className="trace-access-heading">
          <LockKeyhole size={18} />
          <div>
            <strong>Protected telemetry</strong>
            <p>
              Operator credentials are held in memory only.
              They are never saved to browser storage.
            </p>
          </div>
        </div>

        <form className="trace-auth-form" onSubmit={(event) => void loadTraces(event)}>
          <label htmlFor="trace-operator-token">Operator access token</label>
          <div className="trace-auth-controls">
            <input
              id="trace-operator-token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Enter operator bearer token"
              autoComplete="off"
              spellCheck={false}
              disabled={loading}
            />
            <button
              type="submit"
              className="button-primary"
              disabled={!token || loading}
            >
              <RefreshCw size={15} />
              {loading ? 'Loading...' : data ? 'Refresh traces' : 'Unlock traces'}
            </button>
            {(token || data) && (
              <button
                type="button"
                className="button-secondary"
                onClick={lockExplorer}
              >
                Lock
              </button>
            )}
          </div>
        </form>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
          {error.includes('503') &&
            ' Operator authentication must first be configured on the server.'}
        </div>
      )}

      {data && (
        <>
          <div className="trace-metrics">
            <div className="trace-metric">
              <Activity size={18} />
              <span>Recorded spans</span>
              <strong>{data.spans.length}</strong>
            </div>
            <div className="trace-metric">
              <ShieldCheck size={18} />
              <span>Audit events</span>
              <strong>{data.audit_events.length}</strong>
            </div>
            <div className="trace-metric">
              <Clock3 size={18} />
              <span>Timeline entries</span>
              <strong>{timeline.length}</strong>
            </div>
          </div>

          {(data.spans_truncated || data.audit_events_truncated) && (
            <p className="trace-truncated" role="status">
              This view contains the first 100 records per collection.
              Additional records exist.
            </p>
          )}

          {timeline.length === 0 ? (
            <div className="trace-empty">
              <Activity size={24} />
              <strong>No telemetry recorded yet</strong>
              <p>
                The run has no persisted tool spans or audit events.
                No events have been inferred or generated.
              </p>
            </div>
          ) : (
            <div className="trace-workspace">
              <div className="trace-timeline" aria-label="Chronological events">
                <div className="trace-section-heading">
                  <span>EVENT TIMELINE</span>
                  <span>{timeline.length} records</span>
                </div>

                {timeline.map((item, index) => {
                  const isSpan = item.kind === 'span'
                  const title = isSpan
                    ? item.span.name
                    : item.event.event_type
                  const status = isSpan
                    ? item.span.status
                    : item.event.actor_type

                  return (
                    <button
                      key={item.key}
                      type="button"
                      className={`trace-entry ${
                        selected?.key === item.key ? 'is-selected' : ''
                      }`}
                      onClick={() => setSelectedKey(item.key)}
                      aria-pressed={selected?.key === item.key}
                    >
                      <span className="trace-entry-marker" aria-hidden="true" />
                      <span className="trace-entry-content">
                        <span className="trace-entry-topline">
                          <span>#{String(index + 1).padStart(2, '0')}</span>
                          <span>{isSpan ? 'TRACE SPAN' : 'AUDIT EVENT'}</span>
                        </span>
                        <strong>{title}</strong>
                        <span className="trace-entry-meta">
                          {formatTime(item.at)} · {status}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>

              <div className="trace-inspector">
                <div className="trace-section-heading">
                  <span>EVENT INSPECTOR</span>
                  <span>READ ONLY</span>
                </div>

                {selected && (
                  <>
                    <div className="trace-inspector-header">
                      <span className="trace-inspector-type">
                        {selected.kind === 'span' ? 'Execution span' : 'Audit event'}
                      </span>
                      <h3>
                        {selected.kind === 'span'
                          ? selected.span.name
                          : selected.event.event_type}
                      </h3>
                    </div>

                    <dl className="trace-inspector-fields">
                      <div>
                        <dt>Recorded at</dt>
                        <dd>{formatTime(selected.at)}</dd>
                      </div>
                      {selected.kind === 'span' ? (
                        <>
                          <div>
                            <dt>Span type</dt>
                            <dd>{selected.span.span_type}</dd>
                          </div>
                          <div>
                            <dt>Execution status</dt>
                            <dd>{selected.span.status}</dd>
                          </div>
                          <div>
                            <dt>Duration</dt>
                            <dd>{formatDuration(selected.span.duration_ms)}</dd>
                          </div>
                          <div>
                            <dt>Completed at</dt>
                            <dd>
                              {selected.span.ended_at
                                ? formatTime(selected.span.ended_at)
                                : 'Not recorded'}
                            </dd>
                          </div>
                          <div>
                            <dt>Safe outcome</dt>
                            <dd>{selected.span.safe_summary ?? 'Not recorded'}</dd>
                          </div>
                        </>
                      ) : (
                        <>
                          <div>
                            <dt>Actor category</dt>
                            <dd>{selected.event.actor_type}</dd>
                          </div>
                          <div>
                            <dt>Event type</dt>
                            <dd>{selected.event.event_type}</dd>
                          </div>
                        </>
                      )}
                    </dl>
                    <p className="trace-privacy-note">
                      Raw tool arguments, responses, credentials, and audit
                      payloads are intentionally excluded.
                    </p>
                  </>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
