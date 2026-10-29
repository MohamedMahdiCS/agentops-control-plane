import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, RotateCcw } from 'lucide-react'
import type { Agent } from '../api'
import { ConstellationScene } from './constellation/ConstellationScene'
import { placeLabels, type LabelState } from './constellation/labels'

interface AgentTopology3DProps {
  agents: Agent[]
}

const MAX_VISIBLE = 12
const LABEL_MAX_CHARS = 28

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [query])
  return matches
}

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

function truncate(name: string): string {
  return name.length > LABEL_MAX_CHARS ? `${name.slice(0, LABEL_MAX_CHARS - 1)}…` : name
}

export default function AgentTopology3D({ agents }: AgentTopology3DProps) {
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const coarsePointer = useMediaQuery('(pointer: coarse)')
  const stage = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<ConstellationScene | null>(null)
  const labels = useRef<LabelState>({
    elements: new Map(),
    sizes: new Map(),
    selected: null,
    hovered: null,
  })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [webglFailed] = useState(() => !supportsWebGL())

  // Active agents first, then most recently registered.
  const visibleAgents = useMemo(
    () =>
      [...agents]
        .sort(
          (a, b) =>
            Number(b.status === 'active') - Number(a.status === 'active') ||
            b.created_at.localeCompare(a.created_at),
        )
        .slice(0, MAX_VISIBLE),
    [agents],
  )
  const selectedAgent = visibleAgents.find((agent) => agent.id === selectedId) ?? null
  const hasAgents = visibleAgents.length > 0

  const options = useMemo(
    () => ({
      animate: !reducedMotion,
      interactive: !coarsePointer,
      autoRotate: coarsePointer,
      onSelect: setSelectedId,
      onHover: setHoveredId,
      onProject: (points: Parameters<typeof placeLabels>[0], width: number, height: number) =>
        placeLabels(points, width, height, labels.current),
    }),
    [reducedMotion, coarsePointer],
  )
  const optionsRef = useRef(options)

  // Create the WebGL scene once per mount; it is fully disposed on unmount.
  useEffect(() => {
    if (!hasAgents || webglFailed || !stage.current) return
    let scene: ConstellationScene
    try {
      scene = new ConstellationScene(stage.current, optionsRef.current)
    } catch (cause) {
      console.error('Constellation scene could not start', cause)
      return
    }
    sceneRef.current = scene
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(([entry]) => scene.setVisible(entry.isIntersecting), {
            rootMargin: '80px',
          })
    observer?.observe(stage.current)
    return () => {
      observer?.disconnect()
      scene.dispose()
      sceneRef.current = null
    }
  }, [hasAgents, webglFailed])

  useEffect(() => {
    optionsRef.current = options
    sceneRef.current?.setOptions(options)
  }, [options])

  useEffect(() => {
    sceneRef.current?.setAgents(
      visibleAgents.map((agent) => ({ id: agent.id, active: agent.status === 'active' })),
    )
  }, [visibleAgents, hasAgents])

  useEffect(() => {
    labels.current.selected = selectedId
    labels.current.hovered = hoveredId
    sceneRef.current?.setSelected(selectedId)
    sceneRef.current?.setHovered(hoveredId)
  }, [selectedId, hoveredId])

  const activeCount = agents.filter((agent) => agent.status === 'active').length
  const summary = hasAgents
    ? `${visibleAgents.length} agents shown around the control plane core: ${visibleAgents
        .map((agent) => `${agent.name} (${agent.status})`)
        .join(', ')}.`
    : 'No registered agents to display.'

  return (
    <section className="topology-panel" aria-label="3D agent registry">
      <div className="topology-heading">
        <div>
          <span className="eyebrow">INTERACTIVE SYSTEM MAP</span>
          <h2>Agent Registry Constellation</h2>
          <p>
            {coarsePointer
              ? 'Tap an agent to inspect it.'
              : 'Drag to orbit · hover or click an agent to inspect it.'}
          </p>
        </div>
        <div className="topology-heading-actions">
          <span className="count-tag">
            {visibleAgents.length}
            {agents.length > visibleAgents.length ? ` of ${agents.length}` : ''} shown ·{' '}
            {activeCount} active
          </span>
          {!coarsePointer && hasAgents && !webglFailed && (
            <button
              type="button"
              className="topology-reset"
              onClick={() => sceneRef.current?.resetView()}
              aria-label="Reset 3D view"
              title="Reset view"
            >
              <RotateCcw size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="topology-canvas" role="img" aria-label={summary}>
        {!hasAgents ? (
          <div className="topology-empty">
            <Bot size={26} aria-hidden="true" />
            <strong>No agents registered yet</strong>
            <p>Register an agent to see it join the constellation.</p>
          </div>
        ) : webglFailed ? (
          <p className="topology-fallback">
            3D rendering is unavailable on this device. Use the agent list below.
          </p>
        ) : (
          <>
            <div className="topology-stage" ref={stage} />
            <div className="topology-labels" aria-hidden="true">
              {visibleAgents.map((agent) => (
                <span
                  key={agent.id}
                  ref={(element) => {
                    const { elements, sizes } = labels.current
                    if (element) {
                      elements.set(agent.id, element)
                    } else {
                      elements.delete(agent.id)
                      sizes.delete(agent.id)
                    }
                  }}
                  className={`topology-label${agent.id === selectedId ? ' is-selected' : ''}${
                    agent.status === 'active' ? ' is-active' : ''
                  }`}
                  title={agent.name}
                >
                  <span className="topology-label-dot" />
                  {truncate(agent.name)}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="topology-footer">
        <p>Registry membership view. Connections do not represent observed service dependencies.</p>
        {selectedAgent && (
          <dl className="topology-selection" aria-live="polite">
            <div>
              <dt>Selected</dt>
              <dd>{selectedAgent.name}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd className={selectedAgent.status === 'active' ? 'is-active' : ''}>
                {selectedAgent.status}
              </dd>
            </div>
            <div>
              <dt>Config</dt>
              <dd>v{selectedAgent.config_version}</dd>
            </div>
            <div>
              <dt>ID</dt>
              <dd>
                <code>{selectedAgent.id.slice(0, 8)}</code>
              </dd>
            </div>
          </dl>
        )}
      </div>

      {hasAgents && (
        <div className="topology-agent-list" role="group" aria-label="Select an agent">
          {visibleAgents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              aria-pressed={selectedId === agent.id}
              onClick={() => setSelectedId((current) => (current === agent.id ? null : agent.id))}
              onMouseEnter={() => setHoveredId(agent.id)}
              onMouseLeave={() => setHoveredId(null)}
              onFocus={() => setHoveredId(agent.id)}
              onBlur={() => setHoveredId(null)}
            >
              <span
                className={`topology-list-dot${agent.status === 'active' ? ' is-active' : ''}`}
                aria-hidden="true"
              />
              {agent.name}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
