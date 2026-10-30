import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export interface Command {
  id: string
  label: string
  hint?: string
  icon: ReactNode
  run: () => void
}

/** Keyboard-first navigation: Ctrl/⌘+K opens, arrows move, Enter runs. */
export default function CommandPalette({
  open,
  commands,
  onClose,
}: {
  open: boolean
  commands: Command[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const previousFocus = useRef<Element | null>(null)

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return needle
      ? commands.filter((command) => `${command.label} ${command.hint ?? ''}`.toLowerCase().includes(needle))
      : commands
  }, [commands, query])

  useEffect(() => {
    if (!open) return
    previousFocus.current = document.activeElement
    const frame = requestAnimationFrame(() => input.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      ;(previousFocus.current as HTMLElement | null)?.focus?.()
    }
  }, [open])

  if (!open) return null

  function close() {
    setQuery('')
    setActive(0)
    onClose()
  }

  function execute(command: Command | undefined) {
    if (!command) return
    close()
    command.run()
  }

  return (
    <div
      className="ng-palette-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close()
      }}
    >
      <div className="ng-palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          ref={input}
          value={query}
          placeholder="Jump to a view or action…"
          aria-label="Search commands"
          aria-controls="ng-palette-results"
          aria-activedescendant={results[active] ? `ng-cmd-${results[active].id}` : undefined}
          onChange={(event) => {
            setQuery(event.target.value)
            setActive(0)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') close()
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActive((value) => Math.min(value + 1, results.length - 1))
            }
            if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActive((value) => Math.max(value - 1, 0))
            }
            if (event.key === 'Enter') execute(results[active])
          }}
        />
        {results.length === 0 ? (
          <p className="ng-palette-empty">No matching commands.</p>
        ) : (
          <ul id="ng-palette-results" role="listbox">
            {results.map((command, index) => (
              <li key={command.id}>
                <button
                  type="button"
                  id={`ng-cmd-${command.id}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => execute(command)}
                >
                  {command.icon}
                  {command.label}
                  {command.hint && <span>{command.hint}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
