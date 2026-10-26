import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Activity, CircleAlert, Play, RefreshCw } from 'lucide-react'
import {
  getAgentRun,
  submitAgentRun,
  type Agent,
  type AgentRunDetail,
} from '../api'

interface RunConsoleProps {
  agents: Agent[]
}

export default function RunConsole({ agents }: RunConsoleProps) {
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [runId, setRunId] = useState(() => {
    try {
      const saved = sessionStorage.getItem('agentops:last-run-id') ?? ''
      return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(saved)
        ? saved
        : ''
    } catch {
      return ''
    }
  })
  const [run, setRun] = useState<AgentRunDetail | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loadingRun, setLoadingRun] = useState(Boolean(runId))
  const [error, setError] = useState('')
  const retryKey = useRef<string | null>(null)

  const activeAgents = agents.filter((agent) => agent.status === 'active')
  const agentId =
    activeAgents.find((agent) => agent.id === selectedAgentId)?.id ??
    activeAgents[0]?.id ??
    ''

  useEffect(() => {
    if (!runId) return

    const controller = new AbortController()

    getAgentRun(runId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setRun(result)
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Unable to retrieve run.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingRun(false)
      })

    return () => controller.abort()
  }, [runId])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!agentId || submitting) return

    setSubmitting(true)
    setError('')

    if (!retryKey.current) retryKey.current = crypto.randomUUID()

    try {
      const accepted = await submitAgentRun(
        agentId,
        'INC-1042',
        retryKey.current,
      )

      retryKey.current = null
      try {
        sessionStorage.setItem('agentops:last-run-id', accepted.run_id)
      } catch {
        // Run remains accessible while this component is mounted.
      }
      setRun(null)
      setLoadingRun(true)
      setRunId(accepted.run_id)
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'Unable to start investigation.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function refreshRun() {
    if (!runId || loadingRun) return
    setLoadingRun(true)
    setError('')

    try {
      setRun(await getAgentRun(runId))
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'Unable to refresh run.',
      )
    } finally {
      setLoadingRun(false)
    }
  }

  return (
    <section className="panel run-console">
      <div className="panel-heading">
        <div>
          <h2>Investigation Console</h2>
          <p>Submit a real, durable investigation to PostgreSQL.</p>
        </div>
        <span className="count-tag">DETERMINISTIC</span>
      </div>

      <form className="run-form" onSubmit={(event) => void handleSubmit(event)}>
        <label htmlFor="run-agent">Agent</label>
        <select
          id="run-agent"
          value={agentId}
          disabled={submitting || activeAgents.length === 0}
          onChange={(event) => {
            setSelectedAgentId(event.target.value)
            retryKey.current = null
          }}
        >
          {activeAgents.length === 0 && <option value="">No active agents</option>}
          {activeAgents.map((agent) => (
            <option key={agent.id} value={agent.id}>{agent.name}</option>
          ))}
        </select>

        <label htmlFor="run-incident">Incident</label>
        <input id="run-incident" value="INC-1042" readOnly />

        <button
          type="submit"
          className="button-primary"
          disabled={!agentId || submitting}
        >
          <Play size={16} />
          {submitting ? 'Submitting...' : 'Start Investigation'}
        </button>
      </form>

      {error && (
        <div className="alert error" role="alert">
          <CircleAlert size={18} />
          <span>{error}</span>
        </div>
      )}

      {runId && (
        <div className="run-details">
          <div className="panel-heading">
            <div>
              <h2>Latest submitted run</h2>
              <p>{runId}</p>
            </div>
            <button
              type="button"
              className="button-secondary"
              onClick={() => void refreshRun()}
              disabled={loadingRun}
            >
              <RefreshCw size={16} />
              Refresh status
            </button>
          </div>
          {run ? (
            <div className="run-information">
              <p><Activity size={16} /> Status: <strong>{run.status}</strong></p>
              <p>Incident: <strong>{run.incident_id}</strong></p>
              <p>Configuration version: <strong>v{run.agent_config_version}</strong></p>
              <p>Created: <strong>{new Date(run.created_at).toLocaleString()}</strong></p>
              <p>{run.result_summary ?? 'No execution result yet.'}</p>
            </div>
          ) : (
            <p className="pagination-note">
              {loadingRun ? 'Loading persisted run...' : 'Run details unavailable.'}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
