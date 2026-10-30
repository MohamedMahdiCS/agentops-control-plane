import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  Activity,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  CircleAlert,
  Gauge,
  Hexagon,
  KeyRound,
  LayoutDashboard,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import { listAgents, registerAgent, type Agent } from './api'
import CommandPalette, { type Command } from './components/CommandPalette'
import { LiveEventStream, OverviewDataProvider, OverviewKpis } from './components/overview/OverviewLive'
import { useOperator } from './operator-context'
import './App.css'
import './styles/neural-glass.css'

type View = 'overview' | 'agents' | 'runs' | 'evaluations' | 'benchmarks'

const VIEW_META: Record<View, { title: string; description: string }> = {
  overview: {
    title: 'Agents you can prove',
    description: 'Run, govern, evaluate and replay AI agents. Every number here comes from recorded evidence.',
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
  benchmarks: {
    title: 'Benchmarks & Replay',
    description: 'Run reproducible scenario suites, replay them and detect regressions.',
  },
}

function isView(value: string | null): value is View {
  return value !== null && value in VIEW_META
}

const AgentTopology3D = lazy(
  () => import('./components/AgentTopology3D'),
)
const RunConsole = lazy(() => import('./components/RunConsole'))
const EvaluationDashboard = lazy(
  () => import('./components/evaluations/EvaluationDashboard'),
)
const BenchmarkDashboard = lazy(
  () => import('./components/benchmarks/BenchmarkDashboard'),
)

function ViewFallback({ label }: { label: string }) {
  return (
    <section className="panel view-loading" role="status">
      <span className="skeleton skeleton-line" />
      <span className="skeleton skeleton-block" />
      <span className="sr-only">Loading {label}…</span>
    </section>
  )
}

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
  const [paletteOpen, setPaletteOpen] = useState(false)
  const { token, lock } = useOperator()

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function focusUnlock() {
    setView('overview')
    setTimeout(() => document.getElementById('overview-operator-token')?.focus(), 120)
  }

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

  const commands: Command[] = useMemo(
    () => [
      { id: 'overview', label: 'Go to overview', icon: <LayoutDashboard size={16} />, run: () => setView('overview') },
      { id: 'agents', label: 'Go to agent registry', icon: <Bot size={16} />, run: () => setView('agents') },
      { id: 'runs', label: 'Go to runs and traces', icon: <Activity size={16} />, run: () => setView('runs') },
      { id: 'evaluations', label: 'Go to evaluations', icon: <ClipboardCheck size={16} />, run: () => setView('evaluations') },
      { id: 'benchmarks', label: 'Go to benchmarks', icon: <Gauge size={16} />, run: () => setView('benchmarks') },
      { id: 'register', label: 'Register an agent', hint: 'Action', icon: <Plus size={16} />, run: () => { setFormError(''); setShowForm(true) } },
      token
        ? { id: 'lock', label: 'Lock operator mode', hint: 'Security', icon: <LockKeyhole size={16} />, run: lock }
        : { id: 'unlock', label: 'Unlock operator mode', hint: 'Security', icon: <KeyRound size={16} />, run: focusUnlock },
    ],
    // focusUnlock and setters are stable for the palette's purposes.
    [token, lock], // oxlint-disable-line react-hooks/exhaustive-deps
  )

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
          <div className="brand-mark"><Hexagon size={22} /></div>
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

          <button
            type="button"
            className={view === 'benchmarks' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setView('benchmarks')}
          >
            <Gauge size={18} /> Benchmarks
          </button>

          <div className="sidebar-label nav-divider">COMING NEXT</div>
          <div className="nav-item unavailable">
            <ShieldCheck size={18} /> Policy Center <span>SOON</span>
          </div>
          <div className="nav-item unavailable">
            <LockKeyhole size={18} /> Approvals <span>SOON</span>
          </div>
        </nav>

        <div className="ng-system-status" role="status">
          <strong>
            <span className={`ng-pulse ${connected ? '' : 'is-off'}`} aria-hidden="true" />
            {connected ? 'All systems nominal' : loading ? 'Connecting…' : 'API unreachable'}
          </strong>
          <span>FastAPI · PostgreSQL · Worker</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> {view === 'overview' ? 'Overview' : VIEW_META[view].title}</div>
          <div className="ng-topbar-actions">
            <button type="button" className="ng-command" onClick={() => setPaletteOpen(true)} aria-label="Open command palette">
              <Search size={14} aria-hidden="true" />
              <span className="ng-command-label">Search or jump to…</span>
              <kbd>⌘K</kbd>
            </button>
            {token ? (
              <button type="button" className="ng-operator-chip is-unlocked" onClick={lock} title="Lock operator mode">
                <ShieldCheck size={14} aria-hidden="true" /> Operator
              </button>
            ) : (
              <button type="button" className="ng-operator-chip" onClick={focusUnlock} title="Unlock operator mode">
                <KeyRound size={14} aria-hidden="true" /> Locked
              </button>
            )}
            <div className={`connection ${connected ? 'online' : ''}`}>
              <span className="connection-dot" />
              {connected ? 'API online' : loading ? 'Connecting…' : 'API offline'}
            </div>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <div className="eyebrow">{view === 'overview' ? 'AI AGENT CONTROL PLANE' : 'AGENT INFRASTRUCTURE'}</div>
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
            <OverviewDataProvider>
              <OverviewKpis agents={agents} loading={loading} />
              <div className="ng-main-grid">
                <Suspense
                  fallback={
                    <section className="topology-loading" role="status">
                      <span className="topology-loading-orb" aria-hidden="true" />
                      Preparing the agent constellation…
                    </section>
                  }
                >
                  <AgentTopology3D agents={agents} />
                </Suspense>
                <LiveEventStream />
              </div>
            </OverviewDataProvider>
          )}

          {view === 'agents' && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Registered Agents</h2>
                <p>Live records retrieved through the Agent Registry API</p>
              </div>
              <span className="count-tag">{agents.length}{hasMore ? '+' : ''} loaded</span>
            </div>

            {loading && agents.length === 0 ? (
              <div className="skeleton-table" role="status" aria-label="Loading agents">
                {Array.from({ length: 4 }, (_, index) => (
                  <div key={index} className="skeleton-row">
                    <span className="skeleton skeleton-avatar" />
                    <span className="skeleton skeleton-line" />
                    <span className="skeleton skeleton-pill" />
                    <span className="skeleton skeleton-pill" />
                  </div>
                ))}
              </div>
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

          {view === 'runs' && (
            <Suspense fallback={<ViewFallback label="runs" />}>
              <RunConsole agents={agents} />
            </Suspense>
          )}

          {view === 'evaluations' && (
            <Suspense fallback={<ViewFallback label="evaluations" />}>
              <EvaluationDashboard />
            </Suspense>
          )}

          {view === 'benchmarks' && (
            <Suspense fallback={<ViewFallback label="benchmarks" />}>
              <BenchmarkDashboard agents={agents} />
            </Suspense>
          )}

          {view === 'overview' && (
            <section className="roadmap-panel" aria-label="Reliability capabilities">
              <div className="roadmap-heading">
                <ShieldCheck size={20} />
                <div>
                  <h2>Reliability, Replay &amp; Policy Proof</h2>
                  <p>Every capability below runs against real persisted evidence.</p>
                </div>
                <span className="roadmap-badge is-live">LIVE</span>
              </div>
              <div className="capability-grid">
                <button type="button" className="capability-card" onClick={() => setView('runs')}>
                  <Activity size={18} />
                  <strong>Durable runs &amp; traces</strong>
                  <span>Leased workers, checkpoints and an authenticated trace explorer.</span>
                </button>
                <button type="button" className="capability-card" onClick={() => setView('evaluations')}>
                  <ClipboardCheck size={18} />
                  <strong>Deterministic evaluations</strong>
                  <span>Evidence-linked 0–100 scores with safety gates and regression diffs.</span>
                </button>
                <button type="button" className="capability-card" onClick={() => setView('benchmarks')}>
                  <Gauge size={18} />
                  <strong>Benchmarks &amp; replay</strong>
                  <span>Reproducible suites, release gates and behavioural fingerprints.</span>
                </button>
                <div className="capability-card is-static">
                  <LockKeyhole size={18} />
                  <strong>Policy-controlled tools</strong>
                  <span>Gateway authorization, human approvals and expiry recovery.</span>
                </div>
              </div>
            </section>
          )}

          <footer className="page-footer">
            AgentOps Control Plane · Local development environment · Real API data only
          </footer>
        </div>
      </main>

      <CommandPalette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />

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
