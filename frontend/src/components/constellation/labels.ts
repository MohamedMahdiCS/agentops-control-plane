import type { ProjectedPoint } from './ConstellationScene'

const GAP = 16
const EDGE = 8

export interface LabelState {
  elements: Map<string, HTMLElement>
  sizes: Map<string, { width: number; height: number }>
  selected: string | null
  hovered: string | null
}

interface Rect {
  left: number
  top: number
  right: number
  bottom: number
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}

/**
 * Greedy, collision-free label placement in screen space.
 *
 * Labels are clamped inside the canvas so edge nodes stay readable. Selected
 * and hovered labels are always shown; others are placed nearest-first below or
 * above their node and hidden only when every position would overlap. Hidden
 * agents remain reachable through the accessible list below the scene.
 */
export function placeLabels(
  points: ProjectedPoint[],
  width: number,
  height: number,
  state: LabelState,
): void {
  const ranked = points
    .map((point) => ({
      ...point,
      rank: point.id === state.selected ? 0 : point.id === state.hovered ? 1 : 2,
    }))
    .sort((a, b) => a.rank - b.rank || a.depth - b.depth)
  const depths = ranked.map((point) => point.depth)
  const nearest = Math.min(...depths)
  const spread = Math.max(...depths) - nearest || 1
  const placed: Rect[] = []

  for (const point of ranked) {
    const element = state.elements.get(point.id)
    if (!element) continue
    let size = state.sizes.get(point.id)
    if (!size || size.width === 0) {
      size = { width: element.offsetWidth, height: element.offsetHeight }
      state.sizes.set(point.id, size)
    }
    const left = Math.min(Math.max(EDGE, point.x - size.width / 2), width - size.width - EDGE)
    let top: number | null = null
    for (const candidate of [point.y + GAP, point.y - GAP - size.height]) {
      const clamped = Math.min(Math.max(6, candidate), height - size.height - 6)
      const rect = {
        left: left - 4,
        top: clamped - 3,
        right: left + size.width + 4,
        bottom: clamped + size.height + 3,
      }
      if (point.rank < 2 || !placed.some((other) => overlaps(rect, other))) {
        top = clamped
        placed.push(rect)
        break
      }
    }

    if (top === null) {
      element.style.opacity = '0'
      continue
    }
    const nearness = 1 - (point.depth - nearest) / spread
    element.style.opacity = point.rank < 2 ? '1' : (0.8 + nearness * 0.2).toFixed(2)
    element.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`
  }
}
