import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  CircleAlert,
  Download,
  FileJson,
  GitBranch,
  Gauge,
  Play,
  Repeat2,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Timer,
} from 'lucide-react'
import {
  ApiError,
  compareBenchmarks,
  downloadBenchmarkReport,
  getBenchmark,
  listBenchmarks,
  listEvaluationCases,
  replayBenchmark,
  startBenchmark,
  syncEvaluationCatalog,
  type Agent,
  type BenchmarkComparison,
  type BenchmarkDetail,
  type BenchmarkScenario,
  type BenchmarkSummary,
  type EvaluationCase,
  type GateDecision,
  type GateStatus,
} from '../../api'
import OperatorAccess from '../OperatorAccess'
import { useOperator } from '../../operator-context'
import { ScoreBar, VerdictBadge } from '../evaluations/EvaluationPrimitives'
import { formatTimestamp, shortId } from '../evaluations/format'
import '../evaluations/evaluations.css'
import './benchmarks.css'

const GATE_LABEL: Record<GateStatus, string> = {
  passed: 'Passed',
  failed: 'Failed',
  blocked: 'Blocked',
  not_run: 'Not run',
}

function GateBadge({ status }: { status: GateStatus }) {
  const Icon =
    status === 'passed' ? ShieldCheck : status === 'failed' ? ShieldAlert : ShieldQuestion
  return (
    <span className={`bm-gate bm-gate--${status}`}>
      <Icon size={13} aria-hidden="true" /> {GATE_LABEL[status]}
    </span>
  )
}

function GateCard({ title, gate }: { title: string; gate: GateDecision }) {
  return (
    <div className={`bm-gate-card bm-gate-card--${gate.status}`}>
      <div className="bm-gate-card-top">
        <span>{title}</span>
        <GateBadge status={gate.status} />
      </div>
      <ul>
        {gate.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  )
}

function describeError(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) return 'The operator token was rejected.'
    if (cause.status === 503) return 'Operator authentication is not configured on the server.'
    return cause.message
  }
  return cause instanceof Error ? cause.message : fallback
}

function saveFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

/** Single-series magnitude bars with per-bar hover detail; values are measured. */
function MeasuredBars({
  title,
  unit,
  rows,
}: {
  title: string
  unit: string
  rows: { key: string; label: string; value: number | null; detail: string }[]
}) {
  const measured = rows.filter((row) => row.value !== null)
  const max = Math.max(1, ...measured.map((row) => row.value ?? 0))
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <figure className="bm-bars">
      <figcaption>{title}</figcaption>
      {measured.length === 0 ? (
        <p className="ev-muted">Not measured for this benchmark.</p>
      ) : (
        <ul>
          {rows.map((row) => (
            <li
              key={row.key}
              onMouseEnter={() => setHovered(row.key)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(row.key)}
              onBlur={() => setHovered(null)}
              tabIndex={0}
              aria-label={`${row.label}: ${row.value === null ? 'not measured' : `${row.value} ${unit}`}. ${row.detail}`}
            >
              <span className="bm-bar-label">{row.key}</span>
              <span className="bm-bar-track">
                {row.value !== null && (
                  <span
                    className="bm-bar-fill"
                    style={{ width: `${Math.max(2, (row.value / max) * 100)}%` }}
                  />
                )}
              </span>
              <span className="bm-bar-value">
                {row.value === null ? '—' : `${row.value.toLocaleString()} ${unit}`}
              </span>
              {hovered === row.key && (
                <span className="bm-tooltip" role="tooltip">
                  <strong>{row.label}</strong>
                  {row.detail}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </figure>
  )
}

function ScenarioRow({ scenario }: { scenario: BenchmarkScenario }) {
  const perf = scenario.performance
  return (
    <tr>
      <th scope="row">
        <strong>
          {scenario.scenario_key} <small>v{scenario.scenario_version}</small>
        </strong>
        <small className="ev-cell-sub">{scenario.title}</small>
      </th>
      <td>
        {scenario.status === 'completed' ? (
          <VerdictBadge verdict={scenario.verdict} size="sm" />
        ) : (
          <span className="ev-pill ev-pill--unknown">{scenario.status}</span>
        )}
      </td>
      <td className="ev-score-cell">
        <ScoreBar score={scenario.score} threshold={80} label={`${scenario.scenario_key} score`} />
      </td>
      <td>
        <span className="bm-outcome">
          {scenario.run_status ?? '—'}
          {scenario.error_code && <small>{scenario.error_code}</small>}
        </span>
      </td>
      <td className="bm-num">{perf ? perf.tool_requests : '—'}</td>
      <td className="bm-num">{perf ? perf.tool_failures + perf.denied_requests : '—'}</td>
      <td className="bm-num">{perf?.tool_latency_p95_ms ?? '—'}</td>
      <td>
        {scenario.outcome_signature ? (
          <code title={scenario.outcome_signature}>{scenario.outcome_signature.slice(0, 10)}</code>
        ) : (
          '—'
        )}
      </td>
    </tr>
  )
}

export default function BenchmarkDashboard({ agents }: { agents: Agent[] }) {
  const { token, setToken, lock: lockSession } = useOperator()
  const [unlocked, setUnlocked] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [cases, setCases] = useState<EvaluationCase[]>([])
  const [benchmarks, setBenchmarks] = useState<BenchmarkSummary[]>([])
  const [corrupt, setCorrupt] = useState<string[]>([])
  const [selected, setSelected] = useState<BenchmarkDetail | null>(null)
  const [baselineId, setBaselineId] = useState('')
  const [comparison, setComparison] = useState<BenchmarkComparison | null>(null)
  const [busy, setBusy] = useState<'start' | 'replay' | null>(null)

  const activeAgents = agents.filter((agent) => agent.status === 'active')
  const [agentId, setAgentId] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [label, setLabel] = useState('')
  const loadToken = useRef(0)


  const effectiveAgent = activeAgents.find((agent) => agent.id === agentId)?.id ?? activeAgents[0]?.id ?? ''
  const scenarioKeys = useMemo(
    () => [...new Set(cases.map((item) => item.scenario_key))],
    [cases],
  )

  async function refreshList(activeToken: string) {
    const result = await listBenchmarks(activeToken)
    setBenchmarks(result.benchmarks)
    setCorrupt(result.corrupt_manifests)
    return result.benchmarks
  }

  async function openBenchmark(id: string, activeToken = token) {
    const request = ++loadToken.current
    setComparison(null)
    setBaselineId('')
    try {
      const result = await getBenchmark(activeToken, id)
      if (request === loadToken.current) setSelected(result)
    } catch (cause) {
      setError(describeError(cause, 'Unable to load the benchmark.'))
    }
  }

  async function unlock() {
    setLoading(true)
    setError('')
    try {
      await syncEvaluationCatalog(token)
      const caseResult = await listEvaluationCases(token)
      setCases(caseResult.cases)
      const list = await refreshList(token)
      setUnlocked(true)
      if (list[0]) await openBenchmark(list[0].benchmark_run_id, token)
    } catch (cause) {
      setUnlocked(false)
      setError(describeError(cause, 'Unable to load benchmarks.'))
    } finally {
      setLoading(false)
    }
  }

  function lock() {
    loadToken.current += 1
    lockSession()
    setUnlocked(false)
    setBenchmarks([])
    setSelected(null)
    setComparison(null)
    setError('')
    setNotice('')
  }

  // Reuse an operator session unlocked elsewhere in the console.
  useEffect(() => {
    if (!token) return
    const timer = setTimeout(() => void unlock(), 0)
    return () => clearTimeout(timer)
    // Runs once on mount; later token edits wait for an explicit unlock.
  }, []) // oxlint-disable-line react-hooks/exhaustive-deps

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!effectiveAgent || busy) return
    setBusy('start')
    setError('')
    setNotice('')
    try {
      const result = await startBenchmark(token, {
        agent_id: effectiveAgent,
        scenario_keys: chosen.length ? chosen : undefined,
        label: label.trim() || undefined,
      })
      setSelected(result)
      setComparison(null)
      setNotice(`Benchmark "${result.manifest.label}" finished: overall gate ${GATE_LABEL[result.manifest.gates?.overall.status ?? 'not_run'].toLowerCase()}.`)
      setLabel('')
      await refreshList(token)
    } catch (cause) {
      setError(describeError(cause, 'Unable to run the benchmark.'))
    } finally {
      setBusy(null)
    }
  }

  async function replay() {
    if (!selected || busy) return
    const source = selected.manifest.benchmark_run_id
    setBusy('replay')
    setError('')
    try {
      const result = await replayBenchmark(token, source)
      setSelected(result)
      await refreshList(token)
      setBaselineId(source)
      setComparison(await compareBenchmarks(token, result.manifest.benchmark_run_id, source))
      setNotice('Replay finished and was compared with its source benchmark.')
    } catch (cause) {
      setError(describeError(cause, 'Unable to replay the benchmark.'))
    } finally {
      setBusy(null)
    }
  }

  async function compareWith(id: string) {
    setBaselineId(id)
    setComparison(null)
    if (!id || !selected) return
    try {
      setComparison(await compareBenchmarks(token, selected.manifest.benchmark_run_id, id))
    } catch (cause) {
      setError(describeError(cause, 'Unable to compare benchmarks.'))
    }
  }

  async function exportReport() {
    if (!selected) return
    try {
      const text = await downloadBenchmarkReport(
        token,
        selected.manifest.benchmark_run_id,
        baselineId || undefined,
      )
      saveFile(`agentopsbench-${shortId(selected.manifest.benchmark_run_id)}.md`, text, 'text/markdown')
    } catch (cause) {
      setError(describeError(cause, 'Unable to export the report.'))
    }
  }

  const manifest = selected?.manifest
  const others = benchmarks.filter((item) => item.benchmark_run_id !== manifest?.benchmark_run_id)

  return (
    <div className="ev-dashboard">
      <OperatorAccess
        inputId="benchmark-operator-token"
        title="AgentOpsBench Benchmarks & Replay"
        description="Reproducible scenario suites executed through the real worker, gateway and grader."
        recordsLabel="Protected benchmark manifests"
        token={token}
        loading={loading}
        unlocked={unlocked}
        unlockLabel="Unlock benchmarks"
        onTokenChange={setToken}
        onUnlock={() => void unlock()}
        onLock={lock}
      >
        {error && (
          <div className="alert error" role="alert">
            <CircleAlert size={18} />
            <span>{error}</span>
          </div>
        )}
        {notice && (
          <div className="alert success" role="status">
            <ShieldCheck size={18} />
            <span>{notice}</span>
          </div>
        )}
      </OperatorAccess>

      {!unlocked ? (
        <section className="ev-locked">
          <Gauge size={26} aria-hidden="true" />
          <strong>Benchmark manifests are locked</strong>
          <p>
            Unlock with an operator token to run the deterministic suite, replay previous
            benchmarks and detect regressions. Only measured results are displayed.
          </p>
        </section>
      ) : (
        <>
          {corrupt.length > 0 && (
            <div className="alert error" role="alert">
              <ShieldAlert size={18} />
              <span>
                {corrupt.length} manifest(s) failed integrity validation and are not shown:{' '}
                {corrupt.map(shortId).join(', ')}.
              </span>
            </div>
          )}

          <div className="ev-split">
            <section className="panel" aria-label="Benchmark history">
              <div className="panel-heading">
                <div>
                  <h2>Benchmark runs</h2>
                  <p>Checksummed manifests, newest first.</p>
                </div>
                <span className="count-tag">{benchmarks.length} recorded</span>
              </div>
              {benchmarks.length === 0 ? (
                <div className="empty-state">No benchmarks yet. Run the suite to record the first manifest.</div>
              ) : (
                <ul className="bm-runs">
                  {benchmarks.map((item) => (
                    <li key={item.benchmark_run_id}>
                      <button
                        type="button"
                        className={`bm-run ${manifest?.benchmark_run_id === item.benchmark_run_id ? 'is-selected' : ''}`}
                        onClick={() => void openBenchmark(item.benchmark_run_id)}
                        aria-pressed={manifest?.benchmark_run_id === item.benchmark_run_id}
                      >
                        <span className="bm-run-top">
                          <strong>{item.label}</strong>
                          <GateBadge status={item.gate} />
                        </span>
                        <span className="bm-run-meta">
                          {formatTimestamp(item.created_at)} · {item.passed}/{item.scenario_count} passed
                          {item.failed ? ` · ${item.failed} failed` : ''}
                          {item.incomplete ? ` · ${item.incomplete} incomplete` : ''}
                        </span>
                        <span className="bm-run-meta">
                          {item.replay_of && (
                            <span className="ev-pill">
                              <Repeat2 size={11} aria-hidden="true" /> replay of {shortId(item.replay_of)}
                            </span>
                          )}
                          {item.git_commit_sha && (
                            <span className="ev-pill">
                              <GitBranch size={11} aria-hidden="true" /> {item.git_commit_sha.slice(0, 7)}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="panel ev-run-form" aria-label="Run a benchmark">
              <div className="panel-heading">
                <div>
                  <h2>Run the suite</h2>
                  <p>Deterministic simulator scenarios; no external systems are touched.</p>
                </div>
              </div>
              <form onSubmit={(event) => void launch(event)}>
                <label htmlFor="benchmark-agent">Agent</label>
                <select
                  id="benchmark-agent"
                  value={effectiveAgent}
                  onChange={(event) => setAgentId(event.target.value)}
                  disabled={activeAgents.length === 0}
                >
                  {activeAgents.length === 0 && <option value="">No active agents</option>}
                  {activeAgents.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
                <fieldset className="bm-scenarios">
                  <legend>Scenarios (none selected = full suite)</legend>
                  {scenarioKeys.map((key) => {
                    const item = cases.find((c) => c.scenario_key === key)
                    return (
                      <label key={key} className="bm-check">
                        <input
                          type="checkbox"
                          checked={chosen.includes(key)}
                          onChange={(event) =>
                            setChosen((current) =>
                              event.target.checked
                                ? [...current, key]
                                : current.filter((value) => value !== key),
                            )
                          }
                        />
                        <span>
                          <strong>{key}</strong> {item?.title}
                        </span>
                      </label>
                    )
                  })}
                </fieldset>
                <label htmlFor="benchmark-label">Label (optional)</label>
                <input
                  id="benchmark-label"
                  value={label}
                  maxLength={80}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="e.g. Pre-release check"
                />
                <button type="submit" className="button-primary" disabled={!effectiveAgent || busy !== null}>
                  <Play size={15} /> {busy === 'start' ? 'Running suite…' : 'Run benchmark'}
                </button>
              </form>
            </section>
          </div>

          {manifest && selected && (
            <section className="panel bm-detail" aria-label="Benchmark report">
              <div className="panel-heading">
                <div>
                  <h2>{manifest.label}</h2>
                  <p>
                    Suite {manifest.suite_version} · grader v{manifest.grader_version} ·{' '}
                    {manifest.execution_mode} · seed {manifest.seed} · run {shortId(manifest.benchmark_run_id)}
                    {manifest.git_commit_sha && ` · commit ${manifest.git_commit_sha.slice(0, 7)}`}
                    {manifest.git_dirty ? ' (uncommitted changes)' : ''}
                  </p>
                </div>
                <div className="heading-actions">
                  <button type="button" className="button-secondary" onClick={() => void replay()} disabled={busy !== null}>
                    <Repeat2 size={15} /> {busy === 'replay' ? 'Replaying…' : 'Replay'}
                  </button>
                  <button type="button" className="button-secondary" onClick={() => void exportReport()}>
                    <Download size={15} /> Report
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() =>
                      saveFile(
                        `manifest-${shortId(manifest.benchmark_run_id)}.json`,
                        JSON.stringify(manifest, null, 2),
                        'application/json',
                      )
                    }
                  >
                    <FileJson size={15} /> Manifest
                  </button>
                </div>
              </div>

              {manifest.gates && (
                <div className="bm-gates">
                  <GateCard title="Gate A · Platform" gate={manifest.gates.platform} />
                  <GateCard title="Gate B · Agent quality" gate={manifest.gates.agent_quality} />
                  <GateCard title="Overall" gate={manifest.gates.overall} />
                </div>
              )}

              <div className="ev-metric-strip" aria-label="Measured performance">
                <div>
                  <span>Scenarios measured</span>
                  <strong>{selected.performance.scenarios_measured}</strong>
                </div>
                <div>
                  <span>Total active time</span>
                  <strong>{selected.performance.total_active_ms.toLocaleString()} ms</strong>
                </div>
                <div>
                  <span>Tool requests</span>
                  <strong>{selected.performance.total_tool_requests}</strong>
                </div>
                <div>
                  <span>Failed tool calls</span>
                  <strong>{selected.performance.total_tool_failures}</strong>
                </div>
                <div>
                  <span>Slowest tool call</span>
                  <strong>
                    {selected.performance.max_tool_latency_ms === null
                      ? '—'
                      : `${selected.performance.max_tool_latency_ms} ms`}
                  </strong>
                </div>
                <div>
                  <span>Status</span>
                  <strong className="bm-capitalize">{manifest.status}</strong>
                </div>
              </div>

              <div className="table-scroll">
                <table className="agents-table bm-table">
                  <caption className="sr-only">Scenario outcomes</caption>
                  <thead>
                    <tr>
                      <th scope="col">SCENARIO</th>
                      <th scope="col">VERDICT</th>
                      <th scope="col">SCORE</th>
                      <th scope="col">RUN OUTCOME</th>
                      <th scope="col">TOOLS</th>
                      <th scope="col">FAILED/DENIED</th>
                      <th scope="col">P95 MS</th>
                      <th scope="col">SIGNATURE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {manifest.scenarios.map((scenario) => (
                      <ScenarioRow key={scenario.scenario_key} scenario={scenario} />
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="bm-charts">
                <MeasuredBars
                  title="Active execution time per scenario"
                  unit="ms"
                  rows={manifest.scenarios.map((s) => ({
                    key: s.scenario_key,
                    label: s.title,
                    value: s.performance?.active_elapsed_ms ?? null,
                    detail: s.performance
                      ? ` ${s.performance.tool_requests} tool requests, ${s.performance.total_tool_ms} ms inside tools.`
                      : ' Not measured.',
                  }))}
                />
                <MeasuredBars
                  title="Tool-call latency p95 per scenario"
                  unit="ms"
                  rows={manifest.scenarios.map((s) => ({
                    key: s.scenario_key,
                    label: s.title,
                    value: s.performance?.tool_latency_p95_ms ?? null,
                    detail: s.performance
                      ? ` p50 ${s.performance.tool_latency_p50_ms ?? '—'} ms, max ${s.performance.tool_latency_max_ms ?? '—'} ms.`
                      : ' Not measured.',
                  }))}
                />
              </div>
              <p className="bm-footnote">
                <Timer size={13} aria-hidden="true" /> Timings are measured on this machine
                against the in-process simulator. They show relative cost between scenarios,
                not production latency.
              </p>

              {manifest.scenarios.some((s) => s.harness_notes.length || s.failure) && (
                <ul className="bm-notes">
                  {manifest.scenarios.flatMap((s) => [
                    ...s.harness_notes.map((note) => (
                      <li key={`${s.scenario_key}-${note}`}>
                        <strong>{s.scenario_key}</strong> {note}
                      </li>
                    )),
                    ...(s.failure
                      ? [
                          <li key={`${s.scenario_key}-failure`} className="is-failure">
                            <strong>{s.scenario_key}</strong> Execution failure: {s.failure}
                          </li>,
                        ]
                      : []),
                  ])}
                </ul>
              )}

              <div className="bm-compare-head">
                <h3>Regression check</h3>
                <label htmlFor="benchmark-baseline" className="sr-only">
                  Baseline benchmark
                </label>
                <select
                  id="benchmark-baseline"
                  value={baselineId}
                  onChange={(event) => void compareWith(event.target.value)}
                  disabled={others.length === 0}
                >
                  <option value="">{others.length ? 'Compare against a baseline…' : 'No other benchmarks'}</option>
                  {others.map((item) => (
                    <option key={item.benchmark_run_id} value={item.benchmark_run_id}>
                      {item.label} · {formatTimestamp(item.created_at)}
                    </option>
                  ))}
                </select>
              </div>

              {comparison && (
                <div className="bm-comparison">
                  <div className={`ev-compare-banner ${comparison.regression ? 'is-regression' : 'is-stable'}`}>
                    {comparison.regression ? <ShieldAlert size={20} /> : <ShieldCheck size={20} />}
                    <div>
                      <strong>
                        {comparison.regression
                          ? `Regression in ${comparison.regressed_scenarios.join(', ')}`
                          : 'No regression against the baseline'}
                      </strong>
                      <p>
                        {comparison.fully_reproduced
                          ? 'Every comparable scenario reproduced identical behaviour and grading.'
                          : 'Some scenarios produced different behaviour or grading.'}{' '}
                        Baseline gate: {GATE_LABEL[comparison.baseline_gate]} · candidate gate:{' '}
                        {GATE_LABEL[comparison.candidate_gate]}.
                      </p>
                    </div>
                  </div>
                  <div className="table-scroll">
                    <table className="ev-delta-table">
                      <caption className="sr-only">Per-scenario comparison</caption>
                      <thead>
                        <tr>
                          <th scope="col">Scenario</th>
                          <th scope="col">Baseline</th>
                          <th scope="col">Candidate</th>
                          <th scope="col">Δ score</th>
                          <th scope="col">Active ms</th>
                          <th scope="col">Reproduced</th>
                        </tr>
                      </thead>
                      <tbody>
                        {comparison.scenarios.map((row) => (
                          <tr key={row.scenario_key} className={row.regression ? 'bm-regressed' : ''}>
                            <th scope="row">
                              {row.scenario_key}
                              {row.notes.length > 0 && <small className="ev-cell-sub">{row.notes.join('; ')}</small>}
                            </th>
                            <td>
                              {row.baseline_verdict ?? '—'} ({row.baseline_score ?? '—'})
                            </td>
                            <td>
                              {row.candidate_verdict ?? '—'} ({row.candidate_score ?? '—'})
                            </td>
                            <td className={row.score_delta && row.score_delta < 0 ? 'neg' : row.score_delta ? 'pos' : ''}>
                              {row.score_delta === null ? '—' : row.score_delta > 0 ? `+${row.score_delta}` : row.score_delta}
                            </td>
                            <td>
                              {row.baseline_active_ms ?? '—'} → {row.candidate_active_ms ?? '—'}
                            </td>
                            <td>{row.behavior_reproduced ? 'Yes' : 'No'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
