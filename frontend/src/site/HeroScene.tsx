import { useEffect, useRef, useState } from 'react'
import { ConstellationScene } from '../components/constellation/ConstellationScene'
import { placeLabels, type LabelState } from '../components/constellation/labels'

/** Illustrative agents for the landing page hero; not live data. */
const AGENTS = [
  { id: 'production', name: 'Production agent', active: true },
  { id: 'staging', name: 'Staging agent', active: true },
  { id: 'canary', name: 'Canary agent', active: true },
  { id: 'payments', name: 'Payments triage', active: true },
  { id: 'support', name: 'Support agent', active: true },
  { id: 'legacy', name: 'Legacy agent', active: false },
]

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export default function HeroScene() {
  const stage = useRef<HTMLDivElement>(null)
  const labels = useRef<LabelState>({ elements: new Map(), sizes: new Map(), selected: null, hovered: null })
  const [hovered, setHovered] = useState<string | null>(null)

  useEffect(() => {
    if (!stage.current) return
    let scene: ConstellationScene
    try {
      scene = new ConstellationScene(stage.current, {
        animate: !prefersReducedMotion(),
        interactive: !window.matchMedia('(pointer: coarse)').matches,
        autoRotate: true,
        onSelect: () => undefined,
        onHover: (id) => setHovered(id),
        onProject: (points, width, height) => placeLabels(points, width, height, labels.current),
      })
    } catch {
      return
    }
    scene.setAgents(AGENTS.map(({ id, active }) => ({ id, active })))
    const observer = new IntersectionObserver(([entry]) => scene.setVisible(entry.isIntersecting))
    observer.observe(stage.current)
    return () => {
      observer.disconnect()
      scene.dispose()
    }
  }, [])

  useEffect(() => {
    labels.current.hovered = hovered
  }, [hovered])

  return (
    <div className="lp-scene" aria-hidden="true">
      <div className="lp-scene-stage" ref={stage} />
      <div className="lp-scene-labels">
        {AGENTS.map((agent) => (
          <span
            key={agent.id}
            ref={(element) => {
              const { elements, sizes } = labels.current
              if (element) elements.set(agent.id, element)
              else {
                elements.delete(agent.id)
                sizes.delete(agent.id)
              }
            }}
            className={`topology-label${agent.active ? ' is-active' : ''}`}
          >
            <span className="topology-label-dot" />
            {agent.name}
          </span>
        ))}
      </div>
    </div>
  )
}
