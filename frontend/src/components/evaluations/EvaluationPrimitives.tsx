import {
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleMinus,
  CircleX,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
} from 'lucide-react'
import type { EvaluationCheckStatus, EvaluationVerdict } from '../../api'
import { CHECK_LABEL } from './format'

const VERDICT_LABEL: Record<EvaluationVerdict, string> = {
  passed: 'Passed',
  failed: 'Failed',
  inconclusive: 'Inconclusive',
}

export function VerdictBadge({
  verdict,
  size = 'md',
}: {
  verdict: EvaluationVerdict | null
  size?: 'sm' | 'md'
}) {
  if (!verdict) {
    return <span className={`ev-verdict ev-verdict--none ev-verdict--${size}`}>Pending</span>
  }

  const Icon =
    verdict === 'passed' ? CircleCheck : verdict === 'failed' ? CircleX : CircleHelp

  return (
    <span className={`ev-verdict ev-verdict--${verdict} ev-verdict--${size}`}>
      <Icon size={size === 'sm' ? 12 : 14} aria-hidden="true" />
      {VERDICT_LABEL[verdict]}
    </span>
  )
}


export function CheckStatusIcon({ status }: { status: EvaluationCheckStatus }) {
  const Icon =
    status === 'passed'
      ? CircleCheck
      : status === 'failed'
        ? CircleX
        : status === 'unknown'
          ? CircleDashed
          : CircleMinus

  return (
    <span className={`ev-check-icon ev-check-icon--${status}`} title={CHECK_LABEL[status]}>
      <Icon size={16} aria-hidden="true" />
      <span className="sr-only">{CHECK_LABEL[status]}</span>
    </span>
  )
}

export function SafetyGateBadge({ passed }: { passed: boolean | null }) {
  if (passed === null) {
    return (
      <span className="ev-gate ev-gate--unknown">
        <ShieldQuestion size={13} aria-hidden="true" /> Gate pending
      </span>
    )
  }

  return passed ? (
    <span className="ev-gate ev-gate--passed">
      <ShieldCheck size={13} aria-hidden="true" /> Gate passed
    </span>
  ) : (
    <span className="ev-gate ev-gate--failed">
      <ShieldAlert size={13} aria-hidden="true" /> Gate failed
    </span>
  )
}

export function ScoreBar({
  score,
  threshold,
  label,
  showValue = true,
}: {
  score: number | null
  threshold: number
  label: string
  showValue?: boolean
}) {
  const value = score ?? 0
  const tone =
    score === null ? 'none' : score >= threshold ? 'pass' : score >= threshold - 20 ? 'warn' : 'fail'

  return (
    <div className="ev-scorebar">
      <div
        className="ev-scorebar-track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score ?? undefined}
        aria-valuetext={score === null ? 'No score' : `${score} of 100`}
      >
        <span
          className={`ev-scorebar-fill ev-scorebar-fill--${tone}`}
          style={{ width: `${value}%` }}
        />
        <span className="ev-scorebar-threshold" style={{ left: `${threshold}%` }} />
      </div>
      {showValue && <span className="ev-scorebar-value">{score ?? '—'}</span>}
    </div>
  )
}

export function ScoreRing({
  score,
  threshold,
  verdict,
}: {
  score: number | null
  threshold: number
  verdict: EvaluationVerdict | null
}) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const progress = score === null ? 0 : score / 100
  const thresholdAngle = (threshold / 100) * 360 - 90
  const tx = 64 + radius * Math.cos((thresholdAngle * Math.PI) / 180)
  const ty = 64 + radius * Math.sin((thresholdAngle * Math.PI) / 180)

  return (
    <div className={`ev-ring ev-ring--${verdict ?? 'none'}`}>
      <svg viewBox="0 0 128 128" role="img" aria-label={score === null ? 'No score recorded' : `Score ${score} of 100, threshold ${threshold}`}>
        <circle className="ev-ring-track" cx="64" cy="64" r={radius} />
        <circle
          className="ev-ring-value"
          cx="64"
          cy="64"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          transform="rotate(-90 64 64)"
        />
        <circle className="ev-ring-threshold" cx={tx} cy={ty} r="3.5" />
      </svg>
      <div className="ev-ring-label" aria-hidden="true">
        <strong>{score ?? '—'}</strong>
        <span>/ 100</span>
      </div>
    </div>
  )
}
