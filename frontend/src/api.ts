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
