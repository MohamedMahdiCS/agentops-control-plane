import { useState } from 'react'
import { ArrowDownRight, ArrowRight, ArrowUpRight, GitCompareArrows } from 'lucide-react'
import type { EvaluationChange, EvaluationComparison as Comparison } from '../../api'
import { CheckStatusIcon, VerdictBadge } from './EvaluationPrimitives'
import { CHECK_LABEL, shortId } from './format'

function ChangeTag({ change }: { change: EvaluationChange }) {
  const Icon =
    change === 'improved' ? ArrowUpRight : change === 'regressed' ? ArrowDownRight : ArrowRight
  return (
    <span className={`ev-change ev-change--${change}`}>
      <Icon size={13} aria-hidden="true" />
      {change}
    </span>
  )
}

function formatDelta(delta: number | null): string {
  if (delta === null) return '—'
  return delta > 0 ? `+${delta}` : String(delta)
}

export default function EvaluationComparison({ comparison }: { comparison: Comparison }) {
  const [showAll, setShowAll] = useState(false)
  const changed = comparison.checks.filter((check) => check.change !== 'unchanged')
  const checks = showAll ? comparison.checks : changed

  return (
    <section className="ev-compare" aria-label="Regression comparison">
      <div className={`ev-compare-banner ${comparison.regression ? 'is-regression' : 'is-stable'}`}>
        <GitCompareArrows size={20} aria-hidden="true" />
        <div>
          <strong>
            {comparison.regression ? 'Regression detected' : 'No regression detected'}
          </strong>
          <p>
            {comparison.scenario_key} v{comparison.case_version} · grader v
            {comparison.grader_version}
            {comparison.same_evidence
              ? ' · identical evidence fingerprints (reproducibility confirmed)'
              : ' · different run evidence'}
          </p>
        </div>
      </div>

      <div className="ev-compare-grid">
        <div className="ev-compare-side">
          <span>Baseline · run {shortId(comparison.baseline_run_id)}</span>
          <VerdictBadge verdict={comparison.baseline_verdict} size="sm" />
          <strong>{comparison.baseline_score ?? '—'}</strong>
        </div>
        <div className="ev-compare-delta">
          <ChangeTag change={comparison.verdict_change} />
          <strong
            className={
              comparison.score_delta === null
                ? ''
                : comparison.score_delta < 0
                  ? 'neg'
                  : comparison.score_delta > 0
                    ? 'pos'
                    : ''
            }
          >
            {formatDelta(comparison.score_delta)}
          </strong>
          <span>score delta</span>
        </div>
        <div className="ev-compare-side">
          <span>Candidate · run {shortId(comparison.candidate_run_id)}</span>
          <VerdictBadge verdict={comparison.candidate_verdict} size="sm" />
          <strong>{comparison.candidate_score ?? '—'}</strong>
        </div>
      </div>

      {(comparison.new_safety_violations.length > 0 ||
        comparison.resolved_safety_violations.length > 0) && (
        <p className="ev-compare-safety">
          {comparison.new_safety_violations.length > 0 && (
            <>New safety violations: {comparison.new_safety_violations.join(', ')}. </>
          )}
          {comparison.resolved_safety_violations.length > 0 && (
            <>Resolved: {comparison.resolved_safety_violations.join(', ')}.</>
          )}
        </p>
      )}

      <table className="ev-delta-table">
        <caption className="sr-only">Criterion score changes</caption>
        <thead>
          <tr>
            <th scope="col">Criterion</th>
            <th scope="col">Baseline</th>
            <th scope="col">Candidate</th>
            <th scope="col">Delta</th>
          </tr>
        </thead>
        <tbody>
          {comparison.criteria.map((criterion) => (
            <tr key={criterion.key}>
              <th scope="row">{criterion.title}</th>
              <td>{criterion.baseline_score ?? '—'}</td>
              <td>{criterion.candidate_score ?? '—'}</td>
              <td
                className={
                  criterion.delta === null || criterion.delta === 0
                    ? ''
                    : criterion.delta < 0
                      ? 'neg'
                      : 'pos'
                }
              >
                {formatDelta(criterion.delta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="ev-compare-checks-head">
        <h4>
          {showAll ? 'All checks' : `Changed checks (${changed.length})`}
        </h4>
        <button type="button" className="ev-link-button" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show changes only' : 'Show all checks'}
        </button>
      </div>
      {checks.length === 0 ? (
        <p className="ev-muted">Every check produced the same status in both evaluations.</p>
      ) : (
        <ul className="ev-compare-checks">
          {checks.map((check) => (
            <li key={`${check.criterion}:${check.key}`}>
              <span className="ev-compare-check-title">{check.title}</span>
              <span className="ev-compare-check-states">
                <CheckStatusIcon status={check.baseline_status} />
                <ArrowRight size={12} aria-hidden="true" />
                <CheckStatusIcon status={check.candidate_status} />
                <span className="sr-only">
                  {CHECK_LABEL[check.baseline_status]} to {CHECK_LABEL[check.candidate_status]}
                </span>
              </span>
              <ChangeTag change={check.change} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
