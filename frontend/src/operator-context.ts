import { createContext, useContext } from 'react'

/**
 * One operator session for the whole console. The token lives in React memory
 * only: it is never written to browser storage and disappears on reload.
 */
export interface OperatorSession {
  token: string
  setToken: (value: string) => void
  lock: () => void
}

export const OperatorContext = createContext<OperatorSession | null>(null)

export function useOperator(): OperatorSession {
  const session = useContext(OperatorContext)
  if (!session) throw new Error('useOperator must be used inside OperatorProvider')
  return session
}
