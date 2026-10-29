import type { EvaluationCheckStatus } from '../../api'

export const CHECK_LABEL: Record<EvaluationCheckStatus, string> = {
  passed: 'Passed',
  failed: 'Failed',
  unknown: 'Unverified',
  not_applicable: 'Not applicable',
}

export function shortId(value: string): string {
  return value.slice(0, 8)
}

export function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown'
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const CATEGORY_LABEL: Record<string, string> = {
  baseline: 'Baseline',
  operational_failure: 'Operational failure',
  security: 'Security',
  integration: 'Integration',
}
