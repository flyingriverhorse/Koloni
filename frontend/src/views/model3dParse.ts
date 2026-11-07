/**
 * What may take long in reading a 3D model - an STL or OBJ parsed into its arrays - done where it holds
 * nothing up (K-58): in `model3d.worker.ts`, or here where there is no worker. Only the arrays go back,
 * moved and not copied; the materials are made on the page (`model3d.ts`).
 */
// shortcut: three ships no types and @types/three is not installed, so three is `any` here; upgrade by adding it.
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'

export const MAX_TRIANGLES = 2_000_000
export const UNREADABLE = 'It could not be read as a 3D model.'
export const tooMany = (count: number) => `Too many triangles to draw: ${count.toLocaleString()}, over ${MAX_TRIANGLES.toLocaleString()}.`

type Numbers = Float32Array | Uint32Array | Uint16Array | Uint8Array

/** One thing drawn: its arrays, and its materials as the file names them (one, or one for each group). */
export interface Part {
  kind: 'mesh' | 'lines' | 'points'
  name: string
  attributes: Record<string, { array: Numbers; itemSize: number }>
  index: Numbers | null
  groups: { start: number; count: number; materialIndex?: number }[]
  materials: { name: string; flatShading: boolean; vertexColors: boolean }[]
  /** B-341: its box and sphere, measured here: the page does not go over its million points again. */
  bounds: { min: number[]; max: number[]; center: number[]; radius: number } | null
}
/** Its parts, and the .mtl an OBJ names; a string says why it is not drawn. */
export type Parsed = { parts: Part[]; mtl: string | null } | string

function part(kind: Part['kind'], name: string, geometry: any, materials: any[]): Part {
  if (geometry.attributes.position) {
    geometry.computeBoundingBox()
    geometry.computeBoundingSphere()
  }
  const { boundingBox: box, boundingSphere: sphere } = geometry
  return {
    kind,
    name,
    attributes: Object.fromEntries(Object.entries(geometry.attributes).map(([key, value]: [string, any]) => [key, { array: value.array, itemSize: value.itemSize }])),
    index: geometry.index?.array ?? null,
    groups: geometry.groups,
    materials: materials.map(material => ({ name: material.name, flatShading: material.flatShading, vertexColors: material.vertexColors })),
    bounds: box && sphere ? { min: box.min.toArray(), max: box.max.toArray(), center: sphere.center.toArray(), radius: sphere.radius } : null,
  }
}

/** An STL's faces are flat: its normals are drawn from them (flatShading), not sent - half what goes to the GPU (B-341). */
function flat(geometry: any) {
  geometry.deleteAttribute('normal')
  return geometry
}

export function parse(data: ArrayBuffer, ending: string): Parsed {
  try {
    if (ending === 'stl') return { parts: [part('mesh', '', flat(new STLLoader().parse(data)), [])], mtl: null }
    const text = new TextDecoder().decode(data)
    // (counted before it is parsed: each face of n corners is n - 2 triangles)
    let faces = 0
    for (const [, corners] of text.matchAll(/^f\s+(.+)$/gm)) faces += corners.trim().split(/\s+/).length - 2
    if (faces > MAX_TRIANGLES) return tooMany(faces)
    const parts: Part[] = []
    new OBJLoader().parse(text).traverse((child: any) => {
      if (child.geometry) parts.push(part(child.isLineSegments ? 'lines' : child.isPoints ? 'points' : 'mesh', child.name, child.geometry, [child.material].flat()))
    })
    return { parts, mtl: /^mtllib\s+(.+?)\s*$/m.exec(text)?.[1] ?? null }
  } catch {
    return UNREADABLE
  }
}

/** The arrays' buffers, each once (a buffer named twice cannot be moved): what goes back moved. */
export function transferOf(parsed: Parsed): ArrayBuffer[] {
  if (typeof parsed === 'string') return []
  return [...new Set(parsed.parts.flatMap(one => [...Object.values(one.attributes).map(value => value.array), ...(one.index ? [one.index] : [])]).map(array => array.buffer as ArrayBuffer))]
}
