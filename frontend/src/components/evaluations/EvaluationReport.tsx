import { useState } from 'react'
import { ChevronDown, Fingerprint, Link2, ShieldAlert } from 'lucide-react'
import type { EvaluationCriterion, EvaluationDetail } from '../../api'
import {
  CheckStatusIcon,
  SafetyGateBadge,
  ScoreBar,
  ScoreRing,
  VerdictBadge,
} from './EvaluationPrimitives'
import { CHECK_LABEL, formatTimestamp, shortId } from './format'

function CriterionCard({ criterion }: { criterion: EvaluationCriterion }) {
  const [open, setOpen] = useState(
    criterion.checks.some((check) => check.status === 'failed' || check.status === 'unknown'),
  )
  const panelId = `ev-criterion-${criterion.key}`
  const score = criterion.score
  const percent = score === null ? null : Math.round((score / criterion.weight) * 100)

  return (
    <article className="ev-criterion">
      <button
        type="button"
        className="ev-criterion-head"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="ev-criterion-title">
          <strong>{criterion.title}</strong>
          <small>
            {criterion.points_awarded}/{criterion.points_possible} applicable points
          </small>
        </span>
        <span className="ev-criterion-score">
          {score ?? '—'}
          <small>/{criterion.weight}</small>
        </span>
        <ChevronDown size={16} className={open ? 'ev-chevron open' : 'ev-chevron'} aria-hidden="true" />
      </button>
      <ScoreBar
        score={percent}
        threshold={80}
        label={`${criterion.title} score percentage`}
        showValue={false}
      />

      {open && (
        <ul className="ev-checks" id={panelId}>
          {criterion.checks.map((check) => (
            <li key={check.key} className={`ev-check ev-check--${check.status}`}>
              <CheckStatusIcon status={check.status} />
              <div className="ev-check-body">
                <div className="ev-check-top">
                  <strong>{check.title}</strong>
                  <span className="ev-check-points">
                    {check.status === 'not_applicable'
                      ? 'N/A'
                      : `${check.points_awarded}/${check.points_possible}`}
                  </span>
                </div>
                <p>{check.detail}</p>
                <div className="ev-check-meta">
                  <span className={`ev-pill ev-pill--${check.status}`}>
                    {CHECK_LABEL[check.status]}
                  </span>
                  {check.safety_gate && (
                    <span className="ev-pill ev-pill--gate">
                      <ShieldAlert size={11} aria-hidden="true" /> Safety gate
                    </span>
                  )}
                  {check.evidence.length > 0 && (
                    <span className="ev-pill" title={check.evidence.join('\n')}>
                      <Link2 size={11} aria-hidden="true" /> {check.evidence.length} evidence
                      reference{check.evidence.length === 1 ? '' : 's'}
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

export default function EvaluationReport({ detail }: { detail: EvaluationDetail }) {
  const metrics = detail.metrics

  return (
    <div className="ev-report">
      <header className="ev-report-head">
        <ScoreRing
          score={detail.score}
          threshold={detail.passing_threshold}
          verdict={detail.verdict}
        />
        <div className="ev-report-summary">
          <div className="ev-report-badges">
            <VerdictBadge verdict={detail.verdict} />
            <SafetyGateBadge passed={detail.policy_gate_passed} />
            {!detail.evidence_complete && (
              <span className="ev-pill ev-pill--unknown">Evidence incomplete</span>
            )}
          </div>
          <h3>
            {detail.scenario_key} · {detail.scenario_title}
          </h3>
          <p className="ev-report-reason">{detail.verdict_reason}</p>
          <dl className="ev-report-facts">
            <div>
              <dt>Run</dt>
              <dd title={detail.run_id}>{shortId(detail.run_id)}</dd>
            </div>
            <div>
              <dt>Run outcome</dt>
              <dd>
                {String(detail.run_snapshot.status ?? 'unknown')}
                {detail.run_snapshot.error_code
                  ? ` · ${String(detail.run_snapshot.error_code)}`
                  : ''}
              </dd>
            </div>
            <div>
              <dt>Versions</dt>
              <dd>
                scenario v{detail.case_version} · grader v{detail.grader_version}
              </dd>
            </div>
            <div>
              <dt>Recorded</dt>
              <dd>{formatTimestamp(detail.created_at)}</dd>
            </div>
          </dl>
        </div>
      </header>

      <div className="ev-metric-strip" aria-label="Recorded execution metrics">
        <div>
          <span>Tool requests</span>
          <strong>{metrics.tool_requests}</strong>
        </div>
        <div>
          <span>Successful calls</span>
          <strong>{metrics.successful_tool_calls}</strong>
        </div>
        <div>
          <span>Failed attempts</span>
          <strong>{metrics.failed_attempts ?? 'Unknown'}</strong>
        </div>
        <div>
          <span>Denied requests</span>
          <strong>{metrics.denied_requests}</strong>
        </div>
        <div>
          <span>Approvals</span>
          <strong>{metrics.approval_requests}</strong>
        </div>
        <div>
          <span>Linked spans</span>
          <strong>{detail.evidence_span_ids.length}</strong>
        </div>
      </div>

      {detail.safety_gate.violations.length > 0 && (
        <div className="alert error" role="alert">
          <ShieldAlert size={18} />
          <span>
            Safety gate violations: {detail.safety_gate.violations.join(', ')}. A high
            score cannot override a safety violation.
          </span>
        </div>
      )}

      <div className="ev-criteria">
        {detail.criteria.map((criterion) => (
          <CriterionCard key={criterion.key} criterion={criterion} />
        ))}
      </div>

      {detail.evidence_fingerprint && (
        <p className="ev-fingerprint">
          <Fingerprint size={14} aria-hidden="true" />
          Evidence fingerprint
          <code title={detail.evidence_fingerprint}>
            {detail.evidence_fingerprint.slice(0, 16)}…
          </code>
          Regrading identical evidence reproduces this digest.
        </p>
      )}
    </div>
  )
}
