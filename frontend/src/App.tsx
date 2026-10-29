import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  Activity,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  CircleAlert,
  Database,
  LayoutDashboard,
  LockKeyhole,
  Plus,
  RefreshCw,
  ShieldCheck,
  Workflow,
  X,
} from 'lucide-react'
import { listAgents, registerAgent, type Agent } from './api'
import RunConsole from './components/RunConsole'
import EvaluationDashboard from './components/evaluations/EvaluationDashboard'
import './App.css'

type View = 'overview' | 'agents' | 'runs' | 'evaluations'

const VIEW_META: Record<View, { title: string; description: string }> = {
  overview: {
    title: 'Control Plane Overview',
    description: 'Discover, observe, evaluate and secure your AI agents.',
  },
  agents: {
    title: 'Agent Registry',
    description: 'Manage registered agents backed by your PostgreSQL database.',
  },
  runs: {
    title: 'Runs & Traces',
    description: 'Submit durable investigations and inspect real execution status.',
  },
  evaluations: {
    title: 'Evaluations',
    description: 'Grade real runs against versioned scenarios with evidence-linked scores.',
  },
}

function isView(value: string | null): value is View {
  return value !== null && value in VIEW_META
}

const AgentTopology3D = lazy(
  () => import('./components/AgentTopology3D'),
)

function App() {
  const [view, setView] = useState<View>(() => {
    try {
      const saved = sessionStorage.getItem('agentops:active-view')
      return isView(saved) ? saved : 'overview'
    } catch {
      return 'overview'
    }
  })

  useEffect(() => {
    try {
      sessionStorage.setItem('agentops:active-view', view)
    } catch {
      // Navigation remains functional if storage is unavailable.
    }
  }, [view])
  const [agents, setAgents] = useState<Agent[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [creating, setCreating] = useState(false)
  const [formError, setFormError] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const refreshAgents = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await listAgents(signal)
      if (signal?.aborted) return

      setAgents(result.agents)
      setHasMore(result.next_cursor !== null)
      setConnected(true)
      setError('')
    } catch (err) {
      if (signal?.aborted) return

      setConnected(false)
      setError(
        err instanceof Error ? err.message : 'Unable to load agents.',
      )
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    listAgents(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return

        setAgents(result.agents)
        setHasMore(result.next_cursor !== null)
        setConnected(true)
        setError('')
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return

        setConnected(false)
        setError(
          err instanceof Error ? err.message : 'Unable to load agents.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [])

  const activeAgents = agents.filter((agent) => agent.status === 'active').length
  const incidentAgents = agents.filter(
    (agent) => agent.agent_type === 'incident_response',
  ).length

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!name.trim() || creating) return

    setCreating(true)
    setFormError('')

    try {
      const created = await registerAgent({
        name: name.trim(),
        description: description.trim() || undefined,
        agent_type: 'incident_response',
      })

      setShowForm(false)
      setName('')
      setDescription('')
      setNotice(`Agent "${created.name}" registered successfully.`)
      setView('agents')
      await refreshAgents()
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : 'Unable to register agent.',
      )
    } finally {
      setCreating(false)
    }
  }

  function formatDate(value: string) {
    const date = new Date(value)
    return Number.isNaN(date.getTime())
      ? 'Unknown'
      : date.toLocaleString('en-MY', {
          dateStyle: 'medium',
          timeStyle: 'short',
        })
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Workflow size={23} /></div>
          <div>
            <strong>AgentOps</strong>
            <span>CONTROL PLANE</span>
          </div>
        </div>

        <div className="sidebar-label">WORKSPACE</div>
        <nav className="navigation" aria-label="Main navigation">
          <button
            type="button"
            className={view === 'overview' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('overview')}
          >
            <LayoutDashboard size={18} /> Overview
          </button>
          <button
            type="button"
            className={view === 'agents' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('agents')}
          >
            <Bot size={18} /> Agent Registry
          </button>

          <button
            type="button"
            className={view === 'runs' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('runs')}
          >
            <Activity size={18} /> Runs & Traces
          </button>

          <button
            type="button"
            className={view === 'evaluations' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('evaluations')}
          >
            <ClipboardCheck size={18} /> Evaluations
          </button>

          <div className="sidebar-label nav-divider">COMING NEXT</div>
          <div className="nav-item unavailable">
            <ShieldCheck size={18} /> Policy Center <span>SOON</span>
          </div>
          <div className="nav-item unavailable">
            <LockKeyhole size={18} /> Approvals <span>SOON</span>
          </div>
        </nav>

        <div className="sidebar-bottom">
          <span className="environment-dot" />
          LOCAL DEVELOPMENT
          <small>FastAPI · PostgreSQL · React</small>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> {view === 'overview' ? 'Overview' : VIEW_META[view].title}</div>
          <div className={`connection ${connected ? 'online' : ''}`}>
            <span className="connection-dot" />
            {connected ? 'API Connected' : loading ? 'Connecting...' : 'API Disconnected'}
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <div className="eyebrow">AGENT INFRASTRUCTURE</div>
              <h1>{VIEW_META[view].title}</h1>
              <p>{VIEW_META[view].description}</p>
            </div>
            <div className="heading-actions">
              <button
                type="button"
                className="button-secondary"
                disabled={loading}
                onClick={() => {
                  setLoading(true)
                  setError('')
                  void refreshAgents()
                }}
              >
                <RefreshCw size={16} className={loading ? 'spinning' : ''} />
                Refresh
              </button>
              <button
                type="button"
                className="button-primary"
                onClick={() => {
                  setFormError('')
                  setShowForm(true)
                }}
              >
                <Plus size={17} /> Register Agent
              </button>
            </div>
          </section>

          {error && (
            <div className="alert error" role="alert">
              <CircleAlert size={18} />
              <span>{error}. Check whether FastAPI is running on port 8000.</span>
            </div>
          )}

          {notice && (
            <div className="alert success" role="status">
              <CheckCircle2 size={18} />
              <span>{notice}</span>
              <button type="button" aria-label="Dismiss message" onClick={() => setNotice('')}>
                <X size={16} />
              </button>
            </div>
          )}

          {view === 'overview' && (
            <>
              <section className="stats-grid" aria-label="Live statistics">
                <div className="stat-card">
                  <div className="stat-icon blue"><Bot size={19} /></div>
                  <div className="stat-label">Agents loaded</div>
                  <div className="stat-number">{loading && !connected ? '—' : agents.length}{hasMore && '+'}</div>
                  <div className="stat-foot">From the Agent Registry API</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon green"><CheckCircle2 size={19} /></div>
                  <div className="stat-label">Active agents</div>
                  <div className="stat-number">{loading && !connected ? '—' : activeAgents}</div>
                  <div className="stat-foot">Currently registered as active</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon purple"><Activity size={19} /></div>
                  <div className="stat-label">Incident response</div>
                  <div className="stat-number">{loading && !connected ? '—' : incidentAgents}</div>
                  <div className="stat-foot">Agents of this type</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon amber"><Database size={19} /></div>
                  <div className="stat-label">Backend connection</div>
                  <div className="stat-number stat-status">{connected ? 'Online' : loading ? 'Checking' : 'Offline'}</div>
                  <div className="stat-foot">FastAPI / PostgreSQL</div>
                </div>
              </section>

              <Suspense
                fallback={
                  <section className="topology-loading" role="status">
                    Preparing interactive 3D agent constellation...
                  </section>
                }
              >
                <AgentTopology3D agents={agents} />
              </Suspense>

              <div className="section-kicker">LIVE REGISTRY</div>
            </>
          )}

          {(view === 'overview' || view === 'agents') && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Registered Agents</h2>
                <p>Live records retrieved through the Agent Registry API</p>
              </div>
              <span className="count-tag">{agents.length}{hasMore ? '+' : ''} loaded</span>
            </div>

            {loading && agents.length === 0 ? (
              <div className="empty-state">Loading agents from FastAPI...</div>
            ) : agents.length === 0 ? (
              <div className="empty-state">
                No agents loaded. Register your first agent or check the API connection.
              </div>
            ) : (
              <div className="table-scroll">
                <table className="agents-table">
                  <thead>
                    <tr>
                      <th>AGENT</th>
                      <th>TYPE</th>
                      <th>STATUS</th>
                      <th>CONFIG</th>
                      <th>CREATED</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((agent) => (
                      <tr key={agent.id}>
                        <td>
                          <div className="agent-name-cell">
                            <span className="agent-avatar"><Bot size={18} /></span>
                            <div>
                              <strong>{agent.name}</strong>
                              <small>{agent.id.slice(0, 8)}...</small>
                            </div>
                          </div>
                        </td>
                        <td><span className="type-tag">{agent.agent_type}</span></td>
                        <td><span className={`status-tag ${agent.status === 'active' ? 'active' : ''}`}><span />{agent.status}</span></td>
                        <td>v{agent.config_version}</td>
                        <td>{formatDate(agent.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {hasMore && (
              <p className="pagination-note">Showing the first 100 agents. Additional pages are available through the API.</p>
            )}
          </section>
          )}

          {view === 'runs' && <RunConsole agents={agents} />}

          {view === 'evaluations' && <EvaluationDashboard />}

          {view === 'overview' && (
            <section className="roadmap-panel">
              <div className="roadmap-heading">
                <ShieldCheck size={20} />
                <div>
                  <h2>Reliability Replay & Policy Proof</h2>
                  <p>Our signature engineering capability — currently in development.</p>
                </div>
                <span className="roadmap-badge">PLANNED</span>
              </div>
              <div className="roadmap-items">
                <span>Durable execution</span>
                <span>Tool authorization</span>
                <span>Human approvals</span>
                <span>Reproducible evaluations</span>
              </div>
            </section>
          )}

          <footer className="page-footer">
            AgentOps Control Plane · Local development environment · Real API data only
          </footer>
        </div>
      </main>

      {showForm && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-agent-title">
            <div className="modal-header">
              <div>
                <h2 id="create-agent-title">Register new agent</h2>
                <p>Create a real Agent Registry record.</p>
              </div>
              <button type="button" className="icon-button" aria-label="Close dialog" onClick={() => setShowForm(false)} disabled={creating}>
                <X size={20} />
              </button>
            </div>
            <form onSubmit={(event) => void handleCreate(event)}>
              <label htmlFor="agent-name">Agent name</label>
              <input
                id="agent-name"
                required
                minLength={1}
                maxLength={80}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Staging Incident Agent"
              />

              <label htmlFor="agent-description">Description (optional)</label>
              <textarea
                id="agent-description"
                maxLength={500}
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What does this agent do?"
              />

              <label htmlFor="agent-type">Agent type</label>
              <input id="agent-type" value="incident_response" readOnly />

              {formError && <p className="form-error" role="alert">{formError}</p>}

              <div className="form-actions">
                <button type="button" className="button-secondary" onClick={() => setShowForm(false)} disabled={creating}>Cancel</button>
                <button type="submit" className="button-primary" disabled={creating || !name.trim()}>
                  <Plus size={16} /> {creating ? 'Registering...' : 'Register Agent'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  )
}

export default App
