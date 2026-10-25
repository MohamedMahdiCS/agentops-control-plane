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
