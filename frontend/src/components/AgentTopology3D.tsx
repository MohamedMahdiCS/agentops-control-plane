import { useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Float, Html, Line, OrbitControls } from '@react-three/drei'
import { useReducedMotion } from 'motion/react'
import type { Mesh } from 'three'
import type { Agent } from '../api'

interface AgentTopology3DProps {
  agents: Agent[]
}

interface AgentNodeProps {
  agent: Agent
  index: number
  total: number
  reducedMotion: boolean
  selected: boolean
  onSelect: (agentId: string) => void
}

function ConnectionPulse({
  destination,
  offset,
  color,
}: {
  destination: [number, number, number]
  offset: number
  color: string
}) {
  const pulse = useRef<Mesh>(null)

  useFrame(({ clock }) => {
    if (!pulse.current) return

    const progress = (clock.elapsedTime * 0.22 + offset) % 1

    pulse.current.position.set(
      destination[0] * progress,
      destination[1] * progress,
      destination[2] * progress,
    )
  })

  return (
    <mesh ref={pulse}>
      <sphereGeometry args={[0.065, 12, 12]} />
      <meshBasicMaterial color={color} toneMapped={false} />
    </mesh>
  )
}

function AgentNode({
  agent,
  index,
  total,
  reducedMotion,
  selected,
  onSelect,
}: AgentNodeProps) {
  const angle = (index / Math.max(total, 1)) * Math.PI * 2
  const position: [number, number, number] =
    total === 1
      ? [2.4, 0.2, 0]
      : total === 2
        ? [
            index === 0 ? -2.75 : 2.75,
            index === 0 ? 0.6 : -0.4,
            0,
          ]
        : [
            Math.cos(angle) * 2.75,
            Math.sin(angle * 1.5) * 0.65,
            Math.sin(angle) * 1.2,
          ]

  const color = agent.status === 'active' ? '#65D9B1' : '#8292BB'

  return (
    <group>
      <Line
        points={[[0, 0, 0], position]}
        color="#456CB0"
        transparent
        opacity={0.35}
        lineWidth={1}
      />

      {!reducedMotion && (
        <ConnectionPulse
          destination={position}
          offset={index / Math.max(total, 1)}
          color={color}
        />
      )}

      <group position={position}>
        <Float
          speed={reducedMotion ? 0 : 1.4}
          rotationIntensity={reducedMotion ? 0 : 0.18}
          floatIntensity={reducedMotion ? 0 : 0.3}
        >
          {selected && (
            <>
              <mesh scale={1.85}>
                <icosahedronGeometry args={[0.27, 2]} />
                <meshBasicMaterial
                  color={color}
                  transparent
                  opacity={0.15}
                  depthWrite={false}
                />
              </mesh>
              <mesh rotation={[Math.PI / 2, 0, 0]}>
                <torusGeometry args={[0.43, 0.018, 8, 72]} />
                <meshBasicMaterial color={color} />
              </mesh>
            </>
          )}
          <mesh
            scale={selected ? 1.15 : 1}
            onClick={() => onSelect(agent.id)}
          >
            <icosahedronGeometry args={[0.27, 2]} />
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={0.6}
              metalness={0.35}
              roughness={0.2}
            />
          </mesh>

        </Float>

        <Html
            center
            position={[0, -0.53, 0]}
            distanceFactor={9}
            style={{ pointerEvents: 'none' }}
          >
            <span
              style={{
                color: '#DCE7FB',
                fontSize: 12,
                whiteSpace: 'nowrap',
                padding: '4px 8px',
                borderRadius: 6,
                border: '1px solid #40577d',
                background: 'rgba(12, 24, 45, 0.9)',
                textShadow: '0 2px 8px #050B18',
              }}
            >
              {agent.name}
            </span>
          </Html>
      </group>
    </group>
  )
}

function RegistryScene({
  agents,
  reducedMotion,
  selectedId,
  onSelect,
}: {
  agents: Agent[]
  reducedMotion: boolean
  selectedId: string | null
  onSelect: (agentId: string) => void
}) {
  return (
    <>
      <ambientLight intensity={0.65} />
      <pointLight position={[3, 4, 5]} intensity={45} color="#6E9BFF" />
      <pointLight position={[-4, -2, 2]} intensity={18} color="#8D70EF" />

      <Float
        speed={reducedMotion ? 0 : 0.8}
        rotationIntensity={reducedMotion ? 0 : 0.1}
        floatIntensity={reducedMotion ? 0 : 0.2}
      >
        <mesh>
          <icosahedronGeometry args={[0.55, 2]} />
          <meshStandardMaterial
            color="#4978D8"
            emissive="#335DC0"
            emissiveIntensity={0.75}
            metalness={0.65}
            roughness={0.18}
          />
        </mesh>
        <mesh rotation={[Math.PI / 3, 0, 0]}>
          <torusGeometry args={[0.83, 0.012, 8, 96]} />
          <meshBasicMaterial color="#587BCB" transparent opacity={0.6} />
        </mesh>
      </Float>

      {agents.map((agent, index) => (
        <AgentNode
          key={agent.id}
          agent={agent}
          index={index}
          total={agents.length}
          reducedMotion={reducedMotion}
          selected={agent.id === selectedId}
          onSelect={onSelect}
        />
      ))}

      <OrbitControls
        enablePan={false}
        enableZoom={false}
        enableDamping={!reducedMotion}
        autoRotate={false}
        minPolarAngle={Math.PI / 4}
        maxPolarAngle={(Math.PI * 3) / 4}
      />
    </>
  )
}

export default function AgentTopology3D({
  agents,
}: AgentTopology3DProps) {
  const reducedMotion = useReducedMotion() === true
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const visibleAgents = agents.slice(0, 12)
  const selectedAgent = agents.find((agent) => agent.id === selectedId)

  return (
    <section className="topology-panel" aria-label="3D agent registry">
      <div className="topology-heading">
        <div>
          <span className="eyebrow">INTERACTIVE SYSTEM MAP</span>
          <h2>Agent Registry Constellation</h2>
          <p>Explore registered agents in an interactive 3D view.</p>
        </div>
        <span className="count-tag">
          {visibleAgents.length} shown
        </span>
      </div>

      <div className="topology-canvas">
        <Canvas
          camera={{ position: [0, 1.2, 8.5], fov: 48 }}
          dpr={[1, 1.5]}
          gl={{
            antialias: true,
            alpha: true,
            powerPreference: 'low-power',
          }}
          fallback={<p>3D rendering is unavailable on this device.</p>}
        >
          <RegistryScene
            agents={visibleAgents}
            reducedMotion={reducedMotion}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </Canvas>
      </div>

      <div className="topology-footer">
        <p>
          Registry membership visualization — connections do not
          represent observed service dependencies.
        </p>
        {selectedAgent && (
          <p role="status">
            Selected: {selectedAgent.name} · {selectedAgent.status}
          </p>
        )}
      </div>

      <div className="topology-agent-list" aria-label="Select an agent">
        {visibleAgents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            aria-pressed={selectedId === agent.id}
            onClick={() => setSelectedId(agent.id)}
          >
            {agent.name}
          </button>
        ))}
      </div>
    </section>
  )
}
