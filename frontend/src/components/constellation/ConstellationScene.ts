/**
 * Imperative Three.js scene for the Agent Registry Constellation.
 *
 * Named imports keep the 3D chunk tree-shakeable. The scene renders on demand
 * (pointer, resize or state changes) and runs a continuous loop only while
 * motion is allowed and the canvas is on screen.
 */
import {
  AmbientLight,
  BufferGeometry,
  Group,
  IcosahedronGeometry,
  Line,
  LineBasicMaterial,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  PointLight,
  Scene,
  SphereGeometry,
  TorusGeometry,
  Vector3,
  WebGLRenderer,
  type Material,
  type Object3D,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export interface ConstellationAgent {
  id: string
  active: boolean
}

export interface SceneOptions {
  animate: boolean
  interactive: boolean
  autoRotate: boolean
  onSelect: (id: string | null) => void
  onHover: (id: string | null) => void
  /** Called after every rendered frame with each node's projected position. */
  onProject: (points: ProjectedPoint[], width: number, height: number) => void
}

export interface ProjectedPoint {
  id: string
  x: number
  y: number
  depth: number
}

type Vec3 = [number, number, number]

const ACTIVE = 0x65d9b1
const IDLE = 0x8292bb
const LINK = 0x4b6fb3
const FOV = 46

/** Deterministic layout: an ellipse around the core, widest horizontally. */
export function layoutNodes(count: number): Vec3[] {
  if (count === 1) return [[2.6, 0.15, 0.4]]
  const radiusX = count <= 4 ? 3.0 : count <= 8 ? 3.6 : 4.1
  const radiusZ = count <= 4 ? 1.3 : count <= 8 ? 2.1 : 2.5
  return Array.from({ length: count }, (_, index) => {
    const angle = Math.PI + (index / count) * Math.PI * 2
    const lift =
      count <= 2 ? (index === 0 ? 0.35 : -0.25) : index % 2 === 0 ? 0.32 : -0.32
    return [Math.cos(angle) * radiusX, lift, Math.sin(angle) * radiusZ]
  })
}

interface NodeParts {
  id: string
  base: Vec3
  phase: number
  group: Group
  body: Mesh
  bodyMaterial: MeshStandardMaterial
  halo: Group
  ring: Mesh
  link: Line
  linkMaterial: LineBasicMaterial
  pulse: Mesh
  color: number
}

export class ConstellationScene {
  private readonly renderer: WebGLRenderer
  private readonly scene = new Scene()
  private readonly camera = new PerspectiveCamera(FOV, 1, 0.1, 100)
  private readonly controls: OrbitControls
  private readonly core = new Group()
  private readonly projected = new Vector3()
  private readonly resizeObserver: ResizeObserver
  private readonly disposables: { dispose: () => void }[] = []
  private nodes: NodeParts[] = []
  private nodeScale = 1
  private selected: string | null = null
  private hovered: string | null = null
  private visible = true
  private frame = 0
  private renderQueued = false
  private startTime = performance.now()
  private pointerDown: { x: number; y: number } | null = null
  private width = 1
  private height = 1
  private options: SceneOptions
  private readonly container: HTMLElement

  constructor(container: HTMLElement, options: SceneOptions) {
    this.container = container
    this.options = options
    this.renderer = new WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'low-power',
    })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    this.renderer.domElement.setAttribute('aria-hidden', 'true')
    container.appendChild(this.renderer.domElement)

    this.scene.add(new AmbientLight(0xffffff, 0.65))
    const key = new PointLight(0x6e9bff, 45)
    key.position.set(3, 4, 5)
    const fill = new PointLight(0x8d70ef, 18)
    fill.position.set(-4, -2, 2)
    this.scene.add(key, fill)
    this.buildCore()

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enablePan = false
    this.controls.enableZoom = false
    this.controls.minPolarAngle = Math.PI / 3.2
    this.controls.maxPolarAngle = Math.PI / 1.8
    this.controls.autoRotateSpeed = 0.4
    this.controls.addEventListener('change', this.requestRender)

    const canvas = this.renderer.domElement
    canvas.addEventListener('pointermove', this.handlePointerMove)
    canvas.addEventListener('pointerdown', this.handlePointerDown)
    canvas.addEventListener('pointerup', this.handlePointerUp)
    canvas.addEventListener('pointerleave', this.handlePointerLeave)

    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)
    this.resize()
    this.applyOptions()
  }

  setOptions(options: SceneOptions): void {
    this.options = options
    this.applyOptions()
  }

  setVisible(visible: boolean): void {
    this.visible = visible
    this.applyOptions()
  }

  setAgents(agents: ConstellationAgent[]): void {
    for (const node of this.nodes) this.removeNode(node)
    const positions = layoutNodes(agents.length)
    this.nodeScale = agents.length > 8 ? 0.78 : agents.length > 4 ? 0.9 : 1
    this.nodes = agents.map((agent, index) =>
      this.createNode(agent, positions[index], (index / agents.length) * Math.PI * 2),
    )
    // The camera distance depends on how wide the layout is.
    this.resize()
    this.refreshEmphasis()
  }

  setSelected(id: string | null): void {
    this.selected = id
    this.refreshEmphasis()
  }

  setHovered(id: string | null): void {
    this.hovered = id
    this.refreshEmphasis()
  }

  resetView(): void {
    this.controls.reset()
    this.requestRender()
  }

  dispose(): void {
    cancelAnimationFrame(this.frame)
    this.resizeObserver.disconnect()
    const canvas = this.renderer.domElement
    canvas.removeEventListener('pointermove', this.handlePointerMove)
    canvas.removeEventListener('pointerdown', this.handlePointerDown)
    canvas.removeEventListener('pointerup', this.handlePointerUp)
    canvas.removeEventListener('pointerleave', this.handlePointerLeave)
    this.controls.removeEventListener('change', this.requestRender)
    this.controls.dispose()
    for (const node of this.nodes) this.removeNode(node)
    for (const item of this.disposables) item.dispose()
    this.renderer.dispose()
    canvas.remove()
    document.body.style.cursor = ''
  }

  private applyOptions(): void {
    this.controls.enabled = this.options.interactive
    this.controls.enableDamping = this.options.animate
    this.controls.autoRotate = this.options.autoRotate && this.options.animate
    cancelAnimationFrame(this.frame)
    this.frame = 0
    if (this.visible && this.options.animate) {
      this.frame = requestAnimationFrame(this.loop)
    } else {
      this.requestRender()
    }
  }

  private track<T extends { dispose: () => void }>(item: T): T {
    this.disposables.push(item)
    return item
  }

  private buildCore(): void {
    const body = new Mesh(
      this.track(new IcosahedronGeometry(0.55, 2)),
      this.track(
        new MeshStandardMaterial({
          color: 0x4978d8,
          emissive: 0x335dc0,
          emissiveIntensity: 0.75,
          metalness: 0.65,
          roughness: 0.18,
        }),
      ),
    )
    const inner = new Mesh(
      this.track(new TorusGeometry(0.85, 0.011, 8, 96)),
      this.track(new MeshBasicMaterial({ color: 0x8b7dff, transparent: true, opacity: 0.55 })),
    )
    inner.rotation.x = Math.PI / 3
    const outer = new Mesh(
      this.track(new TorusGeometry(1.05, 0.006, 8, 96)),
      this.track(new MeshBasicMaterial({ color: 0x6fd8ff, transparent: true, opacity: 0.3 })),
    )
    outer.rotation.set(-Math.PI / 5, Math.PI / 4, 0)
    this.core.add(body, inner, outer)
    this.scene.add(this.core)
  }

  private createNode(agent: ConstellationAgent, base: Vec3, phase: number): NodeParts {
    const color = agent.active ? ACTIVE : IDLE
    const group = new Group()
    group.position.set(...base)
    group.scale.setScalar(this.nodeScale)

    const bodyMaterial = new MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.55,
      metalness: 0.35,
      roughness: 0.22,
    })
    const body = new Mesh(new IcosahedronGeometry(0.26, 2), bodyMaterial)
    body.userData.agentId = agent.id

    const halo = new Group()
    const glow = new Mesh(
      new IcosahedronGeometry(0.26, 2),
      new MeshBasicMaterial({ color, transparent: true, opacity: 0.13, depthWrite: false }),
    )
    glow.scale.setScalar(1.9)
    const ring = new Mesh(new TorusGeometry(0.44, 0.016, 8, 72), new MeshBasicMaterial({ color }))
    ring.rotation.x = Math.PI / 2
    halo.add(glow, ring)
    halo.visible = false
    group.add(halo, body)

    const linkMaterial = new LineBasicMaterial({ color: LINK, transparent: true, opacity: 0.32 })
    const link = new Line(
      new BufferGeometry().setFromPoints([new Vector3(0, 0, 0), new Vector3(...base)]),
      linkMaterial,
    )
    const pulse = new Mesh(
      new SphereGeometry(0.055, 10, 10),
      new MeshBasicMaterial({ color, toneMapped: false }),
    )
    pulse.visible = this.options.animate

    this.scene.add(link, pulse, group)
    return { id: agent.id, base, phase, group, body, bodyMaterial, halo, ring, link, linkMaterial, pulse, color }
  }

  private removeNode(node: NodeParts): void {
    for (const root of [node.group, node.link, node.pulse] as Object3D[]) {
      this.scene.remove(root)
      root.traverse((object: Object3D) => {
        const mesh = object as Mesh
        mesh.geometry?.dispose()
        const material = mesh.material as Material | Material[] | undefined
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material?.dispose()
      })
    }
  }

  private refreshEmphasis(): void {
    for (const node of this.nodes) {
      const emphasised = node.id === this.selected || node.id === this.hovered
      node.halo.visible = node.id === this.selected
      node.body.scale.setScalar(emphasised ? 1.15 : 1)
      node.bodyMaterial.emissiveIntensity = emphasised ? 0.85 : 0.55
      node.linkMaterial.color.setHex(emphasised ? node.color : LINK)
      node.linkMaterial.opacity = emphasised ? 0.6 : 0.32
    }
    this.requestRender()
  }

  private resize(): void {
    this.width = Math.max(1, this.container.clientWidth)
    this.height = Math.max(1, this.container.clientHeight)
    this.renderer.setSize(this.width, this.height, false)
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.camera.aspect = this.width / this.height
    // Keep the widest node and its label inside the frame at any aspect ratio.
    const halfFov = (FOV * Math.PI) / 360
    // Portrait screens let edge labels clamp inward instead of shrinking the scene.
    const narrow = this.camera.aspect < 1.2 ? 0.72 : 1
    const extent = (this.nodes.length > 8 ? 5.6 : this.nodes.length > 4 ? 5.1 : 4.9) * narrow
    const distance = Math.min(17, Math.max(8.2, extent / (Math.tan(halfFov) * this.camera.aspect)))
    this.camera.position.set(0, distance * 0.48, distance)
    this.camera.lookAt(0, 0, 0)
    this.camera.updateProjectionMatrix()
    this.controls.target.set(0, 0, 0)
    this.controls.update()
    this.controls.saveState()
    this.requestRender()
  }

  private readonly requestRender = (): void => {
    if (this.renderQueued || (this.options.animate && this.visible && this.frame)) return
    if (!this.visible) return
    this.renderQueued = true
    requestAnimationFrame(() => {
      this.renderQueued = false
      this.render(performance.now())
    })
  }

  private readonly loop = (now: number): void => {
    this.render(now)
    this.frame = requestAnimationFrame(this.loop)
  }

  private render(now: number): void {
    const t = (now - this.startTime) / 1000
    const animate = this.options.animate
    if (animate) {
      this.core.rotation.y = t * 0.15
      this.core.position.y = Math.sin(t * 0.7) * 0.05
    }
    for (const node of this.nodes) {
      const bob = animate ? Math.sin(t * 1.1 + node.phase) * 0.07 : 0
      node.group.position.set(node.base[0], node.base[1] + bob, node.base[2])
      if (animate) {
        node.group.rotation.y = t * 0.25 + node.phase
        node.ring.rotation.z = t * 0.6
        const progress = (t * 0.2 + node.phase / (Math.PI * 2)) % 1
        node.pulse.position.set(
          node.base[0] * progress,
          node.base[1] * progress,
          node.base[2] * progress,
        )
      }
      node.pulse.visible = animate
    }
    if (this.controls.enableDamping || this.controls.autoRotate) this.controls.update()
    this.renderer.render(this.scene, this.camera)

    const points = this.nodes.map((node) => {
      this.projected.copy(node.group.position).project(this.camera)
      return {
        id: node.id,
        x: ((this.projected.x + 1) / 2) * this.width,
        y: ((1 - this.projected.y) / 2) * this.height,
        depth: this.projected.z,
      }
    })
    this.options.onProject(points, this.width, this.height)
  }

  /** Nearest node in screen space; generous radius keeps touch targets usable. */
  private pick(event: PointerEvent): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect()
    const x = event.clientX - rect.left
    const y = event.clientY - rect.top
    const radius = event.pointerType === 'mouse' ? 26 : 40
    let best: string | null = null
    let bestDistance = radius
    for (const node of this.nodes) {
      this.projected.copy(node.group.position).project(this.camera)
      const distance = Math.hypot(
        ((this.projected.x + 1) / 2) * this.width - x,
        ((1 - this.projected.y) / 2) * this.height - y,
      )
      if (distance < bestDistance) {
        best = node.id
        bestDistance = distance
      }
    }
    return best
  }

  private readonly handlePointerMove = (event: PointerEvent): void => {
    if (event.pointerType === 'touch') return
    const id = this.pick(event)
    if (id !== this.hovered) {
      this.options.onHover(id)
      document.body.style.cursor = id ? 'pointer' : ''
    }
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.pointerDown = { x: event.clientX, y: event.clientY }
  }

  private readonly handlePointerUp = (event: PointerEvent): void => {
    const start = this.pointerDown
    this.pointerDown = null
    // A drag that orbits the view is not a selection.
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return
    this.options.onSelect(this.pick(event))
  }

  private readonly handlePointerLeave = (): void => {
    if (this.hovered) this.options.onHover(null)
    document.body.style.cursor = ''
  }
}
