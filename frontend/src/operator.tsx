import { useMemo, useState, type ReactNode } from 'react'
import { OperatorContext } from './operator-context'

export function OperatorProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState('')
  const value = useMemo(() => ({ token, setToken, lock: () => setToken('') }), [token])
  return <OperatorContext.Provider value={value}>{children}</OperatorContext.Provider>
}
