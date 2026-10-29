export interface Agent {
  id: string
  name: string
  agent_type: string
  status: string
  config_version: number
  created_at: string
}

export interface AgentListResponse {
  agents: Agent[]
  next_cursor: string | null
}

export interface CreateAgentInput {
  name: string
  description?: string
  agent_type: 'incident_response'
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`API request failed: HTTP ${response.status}`)
  }

  return (await response.json()) as T
}

export async function listAgents(
  signal?: AbortSignal,
): Promise<AgentListResponse> {
  const response = await fetch('/api/v1/agents?limit=100', { signal })
  return parseResponse<AgentListResponse>(response)
}

export async function registerAgent(
  input: CreateAgentInput,
): Promise<Agent> {
  const response = await fetch('/api/v1/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })

  return parseResponse<Agent>(response)
}


export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface AgentRunAccepted {
  run_id: string
  agent_id: string
  incident_id: string
  status: AgentRunStatus
  created_at: string
}

export interface AgentRunDetail extends AgentRunAccepted {
  agent_config_version: number
  started_at: string | null
  finished_at: string | null
  result_summary: string | null
  error: string | null
}

export async function submitAgentRun(
  agentId: string,
  incidentId: string,
  idempotencyKey: string,
): Promise<AgentRunAccepted> {
  const response = await fetch(
    `/api/v1/agents/${encodeURIComponent(agentId)}/runs`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({ incident_id: incidentId }),
    },
  )

  return parseResponse<AgentRunAccepted>(response)
}

export async function getAgentRun(
  runId: string,
  signal?: AbortSignal,
): Promise<AgentRunDetail> {
  const response = await fetch(
    `/api/v1/runs/${encodeURIComponent(runId)}`,
    { signal },
  )

  return parseResponse<AgentRunDetail>(response)
}

export interface RunTraceSpan {
  id: string
  parent_span_id: string | null
  span_type: 'agent_step' | 'tool_call' | 'model_call' | 'policy_check'
  name: string
  status: string
  started_at: string
  ended_at: string | null
  duration_ms: number | null
  safe_summary: string | null
}

export interface RunAuditEvent {
  id: string
  event_type: string
  actor_type: string
  created_at: string
}

export interface RunTraceResponse {
  run_id: string
  spans: RunTraceSpan[]
  audit_events: RunAuditEvent[]
  spans_truncated: boolean
  audit_events_truncated: boolean
}

export async function getRunTraces(
  runId: string,
  operatorToken: string,
  signal?: AbortSignal,
): Promise<RunTraceResponse> {
  if (!operatorToken || operatorToken.trim() !== operatorToken) {
    throw new Error('A valid operator token is required.')
  }

  const response = await fetch(
    `/api/v1/runs/${encodeURIComponent(runId)}/traces`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${operatorToken}`,
      },
      signal,
      cache: 'no-store',
    },
  )

  return parseResponse<RunTraceResponse>(response)
}

// Evaluation engine (operator-authenticated)

export type EvaluationVerdict = 'passed' | 'failed' | 'inconclusive'
export type EvaluationCheckStatus =
  | 'passed'
  | 'failed'
  | 'unknown'
  | 'not_applicable'
export type EvaluationChange = 'improved' | 'regressed' | 'unchanged'

export interface EvaluationCase {
  id: string
  scenario_key: string
  version: number
  category: 'baseline' | 'operational_failure' | 'security' | 'integration'
  title: string
  description: string
  incident_id: string
  agent_quality: boolean
  platform_assertions: boolean
  fault_count: number
  has_injection: boolean
  allowed_terminal_statuses: string[]
  passing_threshold: number
  grader_version: number
  expected_outcome: Record<string, unknown>
  created_at: string
}

export interface EvaluationCheck {
  key: string
  title: string
  status: EvaluationCheckStatus
  points_possible: number
  points_awarded: number
  detail: string
  evidence: string[]
  safety_gate: boolean
}

export interface EvaluationCriterion {
  key: string
  title: string
  weight: number
  points_possible: number
  points_awarded: number
  score: number | null
  checks: EvaluationCheck[]
}

export interface EvaluationSummary {
  id: string
  run_id: string
  scenario_key: string
  scenario_title: string
  category: string
  case_version: number
  grader_version: number
  status: string
  verdict: EvaluationVerdict | null
  score: number | null
  passing_threshold: number
  policy_gate_passed: boolean | null
  evidence_fingerprint: string | null
  created_at: string
  finished_at: string | null
}

export interface EvaluationDetail extends EvaluationSummary {
  verdict_reason: string
  evidence_complete: boolean
  run_snapshot: Record<string, unknown>
  metrics: {
    tool_requests: number
    successful_tool_calls: number
    failed_attempts: number | null
    denied_requests: number
    approval_requests: number
    unknown_points: number
  }
  safety_gate: { passed: boolean | null; violations: string[] }
  criteria: EvaluationCriterion[]
  evidence_span_ids: string[]
}

export interface ScenarioStats {
  scenario_key: string
  version: number
  title: string
  category: string
  total: number
  passed: number
  failed: number
  inconclusive: number
  average_score: number | null
  latest: EvaluationSummary | null
}

export interface EvaluationOverview {
  total: number
  passed: number
  failed: number
  inconclusive: number
  gate_failures: number
  pass_rate: number | null
  average_score: number | null
  scenarios: ScenarioStats[]
}

export interface EvaluationComparison {
  baseline_id: string
  candidate_id: string
  baseline_run_id: string
  candidate_run_id: string
  scenario_key: string
  case_version: number
  grader_version: number
  baseline_verdict: EvaluationVerdict | null
  candidate_verdict: EvaluationVerdict | null
  verdict_change: EvaluationChange
  baseline_score: number | null
  candidate_score: number | null
  score_delta: number | null
  regression: boolean
  same_evidence: boolean
  new_safety_violations: string[]
  resolved_safety_violations: string[]
  criteria: {
    key: string
    title: string
    baseline_score: number | null
    candidate_score: number | null
    delta: number | null
  }[]
  checks: {
    criterion: string
    key: string
    title: string
    baseline_status: EvaluationCheckStatus
    candidate_status: EvaluationCheckStatus
    change: EvaluationChange
  }[]
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail ? `HTTP ${status}: ${detail}` : `API request failed: HTTP ${status}`)
    this.status = status
  }
}

async function operatorRequest<T>(
  path: string,
  operatorToken: string,
  init: RequestInit = {},
): Promise<T> {
  if (!operatorToken || operatorToken.trim() !== operatorToken) {
    throw new Error('A valid operator token is required.')
  }

  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${operatorToken}`)
  if (init.body) headers.set('Content-Type', 'application/json')

  const response = await fetch(path, { ...init, headers, cache: 'no-store' })

  if (!response.ok) {
    let detail = ''
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // Error bodies are optional; the status code is still reported.
    }
    throw new ApiError(response.status, detail)
  }

  return (await response.json()) as T
}

export function syncEvaluationCatalog(token: string, signal?: AbortSignal) {
  return operatorRequest<{ created: number; verified: number }>(
    '/api/v1/evaluations/cases/sync',
    token,
    { method: 'POST', signal },
  )
}

export function listEvaluationCases(token: string, signal?: AbortSignal) {
  return operatorRequest<{ cases: EvaluationCase[] }>(
    '/api/v1/evaluations/cases',
    token,
    { signal },
  )
}

export function getEvaluationOverview(token: string, signal?: AbortSignal) {
  return operatorRequest<EvaluationOverview>(
    '/api/v1/evaluations/overview',
    token,
    { signal },
  )
}

export function listEvaluations(
  token: string,
  filters: { scenario_key?: string; verdict?: string; run_id?: string } = {},
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ limit: '100' })
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  return operatorRequest<{ evaluations: EvaluationSummary[] }>(
    `/api/v1/evaluations?${params.toString()}`,
    token,
    { signal },
  )
}

export function getEvaluation(token: string, id: string, signal?: AbortSignal) {
  return operatorRequest<EvaluationDetail>(
    `/api/v1/evaluations/${encodeURIComponent(id)}`,
    token,
    { signal },
  )
}

export function createEvaluation(
  token: string,
  input: { run_id: string; scenario_key: string },
  idempotencyKey: string,
) {
  return operatorRequest<EvaluationDetail>('/api/v1/evaluations', token, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(input),
  })
}

export function compareEvaluations(
  token: string,
  baselineId: string,
  candidateId: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({
    baseline_id: baselineId,
    candidate_id: candidateId,
  })
  return operatorRequest<EvaluationComparison>(
    `/api/v1/evaluations/compare?${params.toString()}`,
    token,
    { signal },
  )
}
