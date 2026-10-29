import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  ClipboardCheck,
  FlaskConical,
  Gauge,
  Layers,
  LockKeyhole,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sigma,
} from 'lucide-react'
import {
  ApiError,
  compareEvaluations,
  createEvaluation,
  getEvaluation,
  getEvaluationOverview,
  listEvaluationCases,
  listEvaluations,
  syncEvaluationCatalog,
  type EvaluationCase,
  type EvaluationComparison as Comparison,
  type EvaluationDetail,
  type EvaluationOverview,
  type EvaluationSummary,
} from '../../api'
import EvaluationComparison from './EvaluationComparison'
import EvaluationReport from './EvaluationReport'
import { SafetyGateBadge, ScoreBar, VerdictBadge } from './EvaluationPrimitives'
import { CATEGORY_LABEL, formatTimestamp, shortId } from './format'
import './evaluations.css'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function describeError(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) return 'The operator token was rejected.'
    if (cause.status === 503) {
      return 'Operator authentication is not configured on the server.'
    }
    return cause.message
  }
  return cause instanceof Error ? cause.message : fallback
}

function lastRunId(): string {
  try {
    const saved = sessionStorage.getItem('agentops:last-run-id') ?? ''
    return UUID_PATTERN.test(saved) ? saved : ''
  } catch {
    return ''
  }
}

export default function EvaluationDashboard() {
  const [token, setToken] = useState('')
  const [unlocked, setUnlocked] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [cases, setCases] = useState<EvaluationCase[]>([])
  const [overview, setOverview] = useState<EvaluationOverview | null>(null)
  const [history, setHistory] = useState<EvaluationSummary[]>([])
  const [scenarioFilter, setScenarioFilter] = useState('')
  const [verdictFilter, setVerdictFilter] = useState('')

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<EvaluationDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [compareWith, setCompareWith] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [comparing, setComparing] = useState(false)

  const [runId, setRunId] = useState(lastRunId)
  const [scenarioKey, setScenarioKey] = useState('B01')
  const [submitting, setSubmitting] = useState(false)
  const retryKey = useRef<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  // Filter reloads read the current token without refiring on every keystroke.
  const tokenRef = useRef('')

  useEffect(() => () => controller.current?.abort(), [])

  async function refreshData(activeToken: string, signal?: AbortSignal) {
    const [overviewResult, historyResult] = await Promise.all([
      getEvaluationOverview(activeToken, signal),
      listEvaluations(
        activeToken,
        { scenario_key: scenarioFilter, verdict: verdictFilter },
        signal,
      ),
    ])
    setOverview(overviewResult)
    setHistory(historyResult.evaluations)
  }

  async function unlock(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (!token || loading) return

    controller.current?.abort()
    const active = new AbortController()
    controller.current = active
    setLoading(true)
    setError('')

    try {
      await syncEvaluationCatalog(token, active.signal)
      const caseResult = await listEvaluationCases(token, active.signal)
      await refreshData(token, active.signal)
      if (active.signal.aborted) return
      setCases(caseResult.cases)
      setUnlocked(true)
    } catch (cause) {
      if (active.signal.aborted) return
      setUnlocked(false)
      setError(describeError(cause, 'Unable to load evaluations.'))
    } finally {
      if (!active.signal.aborted) setLoading(false)
    }
  }

  function lock() {
    controller.current?.abort()
    tokenRef.current = ''
    setToken('')
    setUnlocked(false)
    setCases([])
    setOverview(null)
    setHistory([])
    setDetail(null)
    setSelectedId(null)
    setComparison(null)
    setError('')
    setNotice('')
  }

  // Reload history whenever filters change after unlocking.
  useEffect(() => {
    const activeToken = tokenRef.current
    if (!unlocked || !activeToken) return
    const active = new AbortController()
    listEvaluations(activeToken, { scenario_key: scenarioFilter, verdict: verdictFilter }, active.signal)
      .then((result) => {
        if (!active.signal.aborted) setHistory(result.evaluations)
      })
      .catch((cause: unknown) => {
        if (!active.signal.aborted) setError(describeError(cause, 'Unable to filter history.'))
      })
    return () => active.abort()
  }, [scenarioFilter, verdictFilter, unlocked])

  async function selectEvaluation(id: string) {
    if (!token) return
    setSelectedId(id)
    setCompareWith('')
    setComparison(null)
    setDetailLoading(true)
    try {
      const result = await getEvaluation(token, id)
      setDetail(result)
    } catch (cause) {
      setDetail(null)
      setError(describeError(cause, 'Unable to load the evaluation report.'))
    } finally {
      setDetailLoading(false)
    }
  }

  async function submitEvaluation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !token) return
    const requestedRun = runId.trim()
    if (!UUID_PATTERN.test(requestedRun)) {
      setError('Enter a valid investigation run ID (UUID).')
      return
    }

    setSubmitting(true)
    setError('')
    setNotice('')
    if (!retryKey.current) retryKey.current = crypto.randomUUID()

    try {
      const result = await createEvaluation(
        token,
        { run_id: requestedRun, scenario_key: scenarioKey },
        retryKey.current,
      )
      retryKey.current = null
      setDetail(result)
      setSelectedId(result.id)
      setComparison(null)
      setCompareWith('')
      setNotice(
        `Recorded ${result.scenario_key} evaluation for run ${shortId(result.run_id)}: ${result.verdict ?? 'pending'}.`,
      )
      await refreshData(token)
    } catch (cause) {
      // A rejected request is not retried with the same key after an input change.
      if (cause instanceof ApiError && cause.status < 500) retryKey.current = null
      setError(describeError(cause, 'Unable to record the evaluation.'))
    } finally {
      setSubmitting(false)
    }
  }

  const compareCandidates = useMemo(
    () =>
      detail
        ? history.filter(
            (item) =>
              item.id !== detail.id &&
              item.scenario_key === detail.scenario_key &&
              item.case_version === detail.case_version &&
              item.grader_version === detail.grader_version,
          )
        : [],
    [detail, history],
  )

  async function runComparison(otherId: string) {
    setCompareWith(otherId)
    setComparison(null)
    if (!otherId || !detail || !token) return
    const other = history.find((item) => item.id === otherId)
    if (!other) return
    // The older evaluation is always the baseline.
    const [baseline, candidate] =
      other.created_at <= detail.created_at ? [other.id, detail.id] : [detail.id, other.id]
    setComparing(true)
    try {
      setComparison(await compareEvaluations(token, baseline, candidate))
    } catch (cause) {
      setError(describeError(cause, 'Unable to compare evaluations.'))
    } finally {
      setComparing(false)
    }
  }

  const selectedCase = cases.find((item) => item.scenario_key === scenarioKey)
  const passRate =
    overview?.pass_rate === null || overview?.pass_rate === undefined
      ? '—'
      : `${Math.round(overview.pass_rate * 100)}%`

  return (
    <div className="ev-dashboard">
      <section className="panel trace-explorer" aria-label="Evaluation access">
        <div className="panel-heading">
          <div>
            <h2>AgentOpsBench Evaluation Engine</h2>
            <p>
              Deterministic, evidence-linked grading of real runs against versioned
              scenarios.
            </p>
          </div>
          <span className="count-tag">
            <ShieldCheck size={13} /> OPERATOR ACCESS
          </span>
        </div>

        <div className="trace-access">
          <div className="trace-access-heading">
            <LockKeyhole size={18} />
            <div>
              <strong>Protected evaluation records</strong>
              <p>
                The operator token stays in memory for this view only and is never
                written to browser storage.
              </p>
            </div>
          </div>
          <form className="trace-auth-form" onSubmit={(event) => void unlock(event)}>
            <label htmlFor="evaluation-operator-token">Operator access token</label>
            <div className="trace-auth-controls">
              <input
                id="evaluation-operator-token"
                type="password"
                value={token}
                onChange={(event) => {
                  tokenRef.current = event.target.value
                  setToken(event.target.value)
                }}
                placeholder="Enter operator bearer token"
                autoComplete="off"
                spellCheck={false}
                disabled={loading}
              />
              <button type="submit" className="button-primary" disabled={!token || loading}>
                <RefreshCw size={15} className={loading ? 'spinning' : ''} />
                {loading ? 'Loading…' : unlocked ? 'Refresh' : 'Unlock evaluations'}
              </button>
              {(token || unlocked) && (
                <button type="button" className="button-secondary" onClick={lock}>
                  Lock
                </button>
              )}
            </div>
          </form>
        </div>

        {error && (
          <div className="alert error" role="alert">
            <ShieldAlert size={18} />
            <span>{error}</span>
          </div>
        )}
        {notice && (
          <div className="alert success" role="status">
            <ClipboardCheck size={18} />
            <span>{notice}</span>
          </div>
        )}
      </section>

      {!unlocked ? (
        <section className="ev-locked" aria-live="polite">
          <FlaskConical size={26} aria-hidden="true" />
          <strong>Evaluation records are locked</strong>
          <p>
            Unlock with an operator token to publish the scenario catalog, grade runs and
            review regression history. No scores are shown until real evaluations exist.
          </p>
        </section>
      ) : (
        <>
          <section className="ev-kpis" aria-label="Evaluation summary">
            <div className="ev-kpi">
              <Layers size={17} aria-hidden="true" />
              <span>Evaluations recorded</span>
              <strong>{overview?.total ?? 0}</strong>
              <small>{cases.length} published scenarios</small>
            </div>
            <div className="ev-kpi">
              <Gauge size={17} aria-hidden="true" />
              <span>Pass rate</span>
              <strong>{passRate}</strong>
              <small>Inconclusive results count as not passed</small>
            </div>
            <div className="ev-kpi">
              <Sigma size={17} aria-hidden="true" />
              <span>Average score</span>
              <strong>{overview?.average_score ?? '—'}</strong>
              <small>Conclusive evaluations only</small>
            </div>
            <div className="ev-kpi">
              <FlaskConical size={17} aria-hidden="true" />
              <span>Inconclusive</span>
              <strong>{overview?.inconclusive ?? 0}</strong>
              <small>Unverified or non-terminal evidence</small>
            </div>
            <div className={`ev-kpi ${overview?.gate_failures ? 'is-alert' : ''}`}>
              <ShieldAlert size={17} aria-hidden="true" />
              <span>Safety gate failures</span>
              <strong>{overview?.gate_failures ?? 0}</strong>
              <small>Unauthorized or unapproved execution</small>
            </div>
          </section>

          <div className="ev-split">
            <section className="panel ev-catalog" aria-label="Scenario catalog">
              <div className="panel-heading">
                <div>
                  <h2>Scenario catalog</h2>
                  <p>Immutable versions; edits require a new version.</p>
                </div>
              </div>
              <ul className="ev-scenarios">
                {overview?.scenarios.map((item) => {
                  const total = item.total || 1
                  return (
                    <li key={`${item.scenario_key}-${item.version}`} className="ev-scenario">
                      <div className="ev-scenario-top">
                        <span className="ev-scenario-key">{item.scenario_key}</span>
                        <div>
                          <strong>{item.title}</strong>
                          <small>
                            {CATEGORY_LABEL[item.category] ?? item.category} · v{item.version}
                          </small>
                        </div>
                        {item.latest ? (
                          <VerdictBadge verdict={item.latest.verdict} size="sm" />
                        ) : (
                          <span className="ev-pill">Not evaluated</span>
                        )}
                      </div>
                      <div
                        className="ev-distribution"
                        role="img"
                        aria-label={`${item.passed} passed, ${item.failed} failed, ${item.inconclusive} inconclusive`}
                      >
                        <span className="pass" style={{ width: `${(item.passed / total) * 100}%` }} />
                        <span className="fail" style={{ width: `${(item.failed / total) * 100}%` }} />
                        <span className="inc" style={{ width: `${(item.inconclusive / total) * 100}%` }} />
                      </div>
                      <div className="ev-scenario-stats">
                        <span>{item.total} runs graded</span>
                        <span>avg {item.average_score ?? '—'}</span>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>

            <section className="panel ev-run-form" aria-label="Evaluate a run">
              <div className="panel-heading">
                <div>
                  <h2>Evaluate a run</h2>
                  <p>Grades persisted evidence only; nothing is executed.</p>
                </div>
              </div>
              <form onSubmit={(event) => void submitEvaluation(event)}>
                <label htmlFor="evaluation-run-id">Investigation run ID</label>
                <input
                  id="evaluation-run-id"
                  value={runId}
                  onChange={(event) => {
                    setRunId(event.target.value)
                    retryKey.current = null
                  }}
                  placeholder="00000000-0000-0000-0000-000000000000"
                  spellCheck={false}
                  autoComplete="off"
                />
                <label htmlFor="evaluation-scenario">Scenario</label>
                <select
                  id="evaluation-scenario"
                  value={scenarioKey}
                  onChange={(event) => {
                    setScenarioKey(event.target.value)
                    retryKey.current = null
                  }}
                >
                  {cases.map((item) => (
                    <option key={item.id} value={item.scenario_key}>
                      {item.scenario_key} v{item.version} — {item.title}
                    </option>
                  ))}
                </select>
                {selectedCase && (
                  <div className="ev-case-brief">
                    <p>{selectedCase.description}</p>
                    <dl>
                      <div>
                        <dt>Permitted outcome</dt>
                        <dd>{selectedCase.allowed_terminal_statuses.join(', ')}</dd>
                      </div>
                      <div>
                        <dt>Threshold</dt>
                        <dd>{selectedCase.passing_threshold}/100 + safety gate</dd>
                      </div>
                      <div>
                        <dt>Scope</dt>
                        <dd>
                          {[
                            selectedCase.agent_quality && 'agent quality',
                            selectedCase.platform_assertions && 'platform assertions',
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </dd>
                      </div>
                    </dl>
                  </div>
                )}
                <button type="submit" className="button-primary" disabled={submitting || !runId}>
                  <Play size={15} />
                  {submitting ? 'Grading…' : 'Record evaluation'}
                </button>
              </form>
            </section>
          </div>

          <section className="panel ev-history" aria-label="Evaluation history">
            <div className="panel-heading">
              <div>
                <h2>Evaluation history</h2>
                <p>Append-only results, newest first.</p>
              </div>
              <div className="ev-filters">
                <label className="sr-only" htmlFor="evaluation-filter-scenario">
                  Filter by scenario
                </label>
                <select
                  id="evaluation-filter-scenario"
                  value={scenarioFilter}
                  onChange={(event) => setScenarioFilter(event.target.value)}
                >
                  <option value="">All scenarios</option>
                  {[...new Set(cases.map((item) => item.scenario_key))].map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </select>
                <label className="sr-only" htmlFor="evaluation-filter-verdict">
                  Filter by verdict
                </label>
                <select
                  id="evaluation-filter-verdict"
                  value={verdictFilter}
                  onChange={(event) => setVerdictFilter(event.target.value)}
                >
                  <option value="">All verdicts</option>
                  <option value="passed">Passed</option>
                  <option value="failed">Failed</option>
                  <option value="inconclusive">Inconclusive</option>
                </select>
              </div>
            </div>

            {history.length === 0 ? (
              <div className="empty-state">
                No evaluations recorded{scenarioFilter || verdictFilter ? ' for these filters' : ''}.
                Grade a completed run to create the first result.
              </div>
            ) : (
              <div className="table-scroll">
                <table className="agents-table ev-table">
                  <thead>
                    <tr>
                      <th scope="col">VERDICT</th>
                      <th scope="col">SCORE</th>
                      <th scope="col">SCENARIO</th>
                      <th scope="col">RUN</th>
                      <th scope="col">SAFETY</th>
                      <th scope="col">RECORDED</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((item) => (
                      <tr
                        key={item.id}
                        className={item.id === selectedId ? 'is-selected' : ''}
                      >
                        <td>
                          <button
                            type="button"
                            className="ev-row-button"
                            onClick={() => void selectEvaluation(item.id)}
                            aria-pressed={item.id === selectedId}
                            aria-label={`Open ${item.scenario_key} evaluation for run ${shortId(item.run_id)}`}
                          >
                            <VerdictBadge verdict={item.verdict} size="sm" />
                          </button>
                        </td>
                        <td className="ev-score-cell">
                          <ScoreBar
                            score={item.score}
                            threshold={item.passing_threshold}
                            label={`Score for ${item.scenario_key}`}
                          />
                        </td>
                        <td>
                          <strong>{item.scenario_key}</strong>
                          <small className="ev-cell-sub">{item.scenario_title}</small>
                        </td>
                        <td>
                          <code title={item.run_id}>{shortId(item.run_id)}</code>
                        </td>
                        <td>
                          <SafetyGateBadge passed={item.policy_gate_passed} />
                        </td>
                        <td>{formatTimestamp(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {(detail || detailLoading) && (
            <section className="panel ev-detail" aria-label="Evaluation report" aria-busy={detailLoading}>
              <div className="panel-heading">
                <div>
                  <h2>Evaluation report</h2>
                  <p>Every check cites recorded evidence or is marked unverified.</p>
                </div>
                {detail && compareCandidates.length > 0 && (
                  <div className="ev-filters">
                    <label htmlFor="evaluation-compare">Compare with</label>
                    <select
                      id="evaluation-compare"
                      value={compareWith}
                      onChange={(event) => void runComparison(event.target.value)}
                    >
                      <option value="">Select an evaluation…</option>
                      {compareCandidates.map((item) => (
                        <option key={item.id} value={item.id}>
                          {shortId(item.run_id)} · {item.verdict ?? 'pending'} · {item.score ?? '—'} ·{' '}
                          {formatTimestamp(item.created_at)}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
              {detailLoading || !detail ? (
                <div className="ev-skeleton" role="status">
                  Loading evaluation report…
                </div>
              ) : (
                <>
                  {comparing && (
                    <div className="ev-skeleton" role="status">
                      Comparing evaluations…
                    </div>
                  )}
                  {comparison && <EvaluationComparison comparison={comparison} />}
                  <EvaluationReport detail={detail} />
                </>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
