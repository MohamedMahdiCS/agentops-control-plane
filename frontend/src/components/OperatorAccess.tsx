import type { FormEvent, ReactNode } from 'react'
import { LockKeyhole, RefreshCw, ShieldCheck } from 'lucide-react'

interface OperatorAccessProps {
  inputId: string
  title: string
  description: string
  recordsLabel: string
  token: string
  loading: boolean
  unlocked: boolean
  unlockLabel: string
  onTokenChange: (value: string) => void
  onUnlock: () => void
  onLock: () => void
  children?: ReactNode
}

/** Operator token entry. The token lives in component memory only. */
export default function OperatorAccess({
  inputId,
  title,
  description,
  recordsLabel,
  token,
  loading,
  unlocked,
  unlockLabel,
  onTokenChange,
  onUnlock,
  onLock,
  children,
}: OperatorAccessProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token && !loading) onUnlock()
  }

  if (unlocked) {
    return (
      <section className="panel ng-access-compact" aria-label={`${title} access`}>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <div className="ng-access-actions">
          <span className="ng-operator-chip is-unlocked">
            <ShieldCheck size={14} aria-hidden="true" /> Operator session active
          </span>
          <button type="button" className="button-secondary" onClick={onUnlock} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'spinning' : ''} /> Refresh
          </button>
          <button type="button" className="button-secondary" onClick={onLock}>
            Lock
          </button>
        </div>
        {children}
      </section>
    )
  }

  return (
    <section className="panel trace-explorer" aria-label={`${title} access`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="count-tag">
          <ShieldCheck size={13} /> OPERATOR ACCESS
        </span>
      </div>

      <div className="trace-access">
        <div className="trace-access-heading">
          <LockKeyhole size={18} />
          <div>
            <strong>{recordsLabel}</strong>
            <p>
              The operator token stays in memory for this view only and is never
              written to browser storage.
            </p>
          </div>
        </div>
        <form className="trace-auth-form" onSubmit={submit}>
          <label htmlFor={inputId}>Operator access token</label>
          <div className="trace-auth-controls">
            <input
              id={inputId}
              type="password"
              value={token}
              onChange={(event) => onTokenChange(event.target.value)}
              placeholder="Enter operator bearer token"
              autoComplete="off"
              spellCheck={false}
              disabled={loading}
            />
            <button type="submit" className="button-primary" disabled={!token || loading}>
              <RefreshCw size={15} className={loading ? 'spinning' : ''} />
              {loading ? 'Loading…' : unlocked ? 'Refresh' : unlockLabel}
            </button>
            {(token || unlocked) && (
              <button type="button" className="button-secondary" onClick={onLock}>
                Lock
              </button>
            )}
          </div>
        </form>
      </div>
      {children}
    </section>
  )
}
