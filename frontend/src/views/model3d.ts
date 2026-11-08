/**
 * A 3D model read for the Files window's view (slice 58, `ModelView`): fetched from its address in
 * the app and parsed by its name - STL, OBJ (with the .mtl it names), glTF / GLB or 3MF - with what
 * it names beside it read from its own folder only; and the arithmetic of the view's keys.
 */
// shortcut: three ships no types and @types/three is not installed, so three is `any` here; upgrade by adding it.
import * as THREE from 'three'
import { unzipSync } from 'three/examples/jsm/libs/fflate.module.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { MTLLoader } from 'three/examples/jsm/loaders/MTLLoader.js'
import { MAX_TRIANGLES, type Parsed, type Part, UNREADABLE, parse, tooMany } from './model3dParse'

export { MAX_TRIANGLES }

/** As the server's `views.MAX_MODEL_BYTES`. */
const MAX_BYTES = 50 * 1024 * 1024
const TOO_LARGE = 'Too large to draw: over 50 MB.'
/**
 * What a model may unpack to - a 3MF's files, a glTF's arrays - before it is read: a small file can
 * ask for gigabytes (a zip's or an accessor's declared size) and take the tab down. Four times the
 * largest file served: a glTF's arrays may read the same bytes more than once, and come from beside it.
 */
const MAX_UNPACKED = 4 * MAX_BYTES
const TOO_LARGE_UNPACKED = 'Too large to draw: it unpacks to over 200 MB.'
/** The most files a model may name beside it: each may be as large as itself. */
const MAX_BESIDE = 32
/** What a glTF's files beside it may come to, all together (K-58): as much as it may unpack to. */
const TOO_LARGE_BESIDE = 'Too large to show here: the files beside it come to over 200 MB.'
const REFUSED = 'about:blank' // (a resource refused: it fails to load, and nothing is asked for)
const STEP = Math.PI / 18
const UNITS: Record<string, string> = { micron: 'µm', millimeter: 'mm', centimeter: 'cm', meter: 'm', inch: 'in', foot: 'ft' }

/**
 * Only what lies in the model's own folder, on this origin, or what it carries in itself: no query
 * or fragment (the same file again under another address), no slash written as %2f or %5c (the
 * server refuses those too), and no more than MAX_BESIDE files.
 */
export function guard(base: string) {
  const folder = new URL(base)
  const asked = new Set<string>()
  return (url: string) => {
    if (/^(data|blob):/i.test(url)) return url
    const full = new URL(url, folder)
    if (full.origin !== folder.origin || !full.pathname.startsWith(folder.pathname) || full.search || full.hash || /%2f|%5c/i.test(full.pathname)) return REFUSED
    asked.add(full.href)
    return asked.size > MAX_BESIDE ? REFUSED : full.href
  }
}

/** The triangles of what is drawn. */
export function triangles(object: THREE.Object3D) {
  let count = 0
  object.traverse((part: THREE.Mesh) => {
    if (part.isMesh) count += (Math.floor((part.geometry.index ?? part.geometry.attributes.position)?.count / 3) || 0) * (part.isInstancedMesh ? part.count : 1)
  })
  return count
}

/** Where the camera goes, from where it is (as an offset from what it looks at), for a key; null: not a key of the view. */
export function step(key: string, offset: THREE.Vector3): THREE.Vector3 | null {
  const turn = new THREE.Spherical().setFromVector3(offset)
  if (key === 'ArrowLeft') turn.theta -= STEP
  else if (key === 'ArrowRight') turn.theta += STEP
  else if (key === 'ArrowUp') turn.phi -= STEP
  else if (key === 'ArrowDown') turn.phi += STEP
  else if (key === '+' || key === '=') turn.radius *= 0.8
  else if (key === '-' || key === '−') turn.radius *= 1.25
  else return null
  turn.makeSafe()
  return new THREE.Vector3().setFromSpherical(turn)
}

export interface Loaded {
  object: THREE.Object3D
  bytes: number
  /** What its file says it is measured in; null where it says nothing. */
  unit: string | null
  triangles: number
}

const ITEM = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT2: 4, MAT3: 9, MAT4: 16 } as Record<string, number>
const COMPONENT = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 } as Record<number, number>

/** A glTF's JSON - the .gltf itself, or a GLB's first chunk; null where there is none. */
function gltfJson(data: ArrayBuffer) {
  const view = new DataView(data)
  const glb = data.byteLength >= 20 && view.getUint32(0, true) === 0x46546c67
  const bytes = glb ? new Uint8Array(data, 20, Math.min(view.getUint32(12, true), data.byteLength - 20)) : new Uint8Array(data)
  try {
    return JSON.parse(new TextDecoder().decode(bytes))
  } catch {
    return null
  }
}

/**
 * Whether a glTF's arrays ask for more than MAX_UNPACKED: three makes an array of an accessor's
 * declared size where no buffer holds it (no bufferView), so the JSON alone can ask for gigabytes.
 * One with neither a bufferView nor sparse values is all zeros - nothing to draw - and refused.
 */
export function gltfTooLarge(json: { accessors?: { bufferView?: number; sparse?: object; count?: number; type?: string; componentType?: number }[] } | null) {
  let bytes = 0
  for (const accessor of json?.accessors ?? []) {
    const count = Number(accessor.count)
    if ((accessor.bufferView === undefined && accessor.sparse === undefined) || !(count >= 0)) return true
    bytes += count * (ITEM[accessor.type ?? ''] ?? 16) * (COMPONENT[accessor.componentType ?? 0] ?? 4)
  }
  return bytes > MAX_UNPACKED
}

/**
 * A glTF's files beside it (buffers, images), read before it is parsed so that their sum is known: as blob
 * addresses, by the address the loader asks for. What `check` refuses, or cannot be read, is left out - it
 * fails to load, as it would. A string says why it is not drawn.
 */
async function besideOf(json: { buffers?: { uri?: string }[]; images?: { uri?: string }[] } | null, base: string, check: (url: string) => string, signal?: AbortSignal) {
  const read = new Map<string, Blob>()
  let total = 0
  for (const { uri } of [...(json?.buffers ?? []), ...(json?.images ?? [])]) {
    // (the address as GLTFLoader makes it: its folder and the uri, side by side)
    if (typeof uri !== 'string' || /^(data|blob):/i.test(uri) || read.has(base + uri) || check(base + uri) === REFUSED) continue
    const answer = await fetch(check(base + uri), { signal }).catch(() => null)
    const bytes = answer?.ok ? await answer.blob().catch(() => null) : null
    if (!bytes) continue
    if ((total += bytes.size) > MAX_UNPACKED) return TOO_LARGE_BESIDE
    read.set(base + uri, bytes)
  }
  return new Map([...read].map(([url, bytes]) => [url, URL.createObjectURL(bytes)]))
}

/** STL and OBJ parsed in a worker, so that a large one does not hold the page (K-58); here, where there is none. */
function offThread(data: ArrayBuffer, ending: string, signal?: AbortSignal): Promise<Parsed> {
  if (typeof Worker === 'undefined') return Promise.resolve(parse(data, ending))
  return new Promise(resolve => {
    const worker = new Worker(new URL('./model3d.worker.ts', import.meta.url), { type: 'module' })
    const done = (parsed: Parsed) => {
      worker.terminate()
      signal?.removeEventListener('abort', stop)
      resolve(parsed)
    }
    const stop = () => done(UNREADABLE) // (no longer wanted: nothing of it is shown)
    worker.onmessage = (event: MessageEvent<Parsed>) => done(event.data)
    worker.onerror = worker.onmessageerror = () => done(UNREADABLE)
    signal?.addEventListener('abort', stop)
    worker.postMessage({ data, ending }, [data])
  })
}

/** B-341: the triangles of one piece of a large STL - each piece's arrays go to the GPU on a frame of their own (`ModelView`). */
export const PIECE = 200_000

/** What the worker parsed, as three draws it: an STL in its one colour, an OBJ's parts with the .mtl's materials by name. */
function built({ parts }: Exclude<Parsed, string>, ending: string, mtl: { create(name: string): THREE.Material | undefined } | null): THREE.Object3D {
  // (its arrays as they came, never copied; its box and sphere as the worker measured them)
  const geometry = (one: Part, cut?: [number, number]) => {
    const made = new THREE.BufferGeometry()
    for (const [key, { array, itemSize }] of Object.entries(one.attributes)) made.setAttribute(key, new THREE.BufferAttribute(cut ? array.subarray(...cut) : array, itemSize))
    if (one.index) made.setIndex(new THREE.BufferAttribute(one.index, 1))
    for (const { start, count, materialIndex } of one.groups) made.addGroup(start, count, materialIndex)
    // (a piece takes the whole's: their union is the whole, and none is culled that is in sight)
    if (one.bounds) {
      made.boundingBox = new THREE.Box3().setFromArray([...one.bounds.min, ...one.bounds.max])
      made.boundingSphere = new THREE.Sphere(new THREE.Vector3().fromArray(one.bounds.center), one.bounds.radius)
    }
    return made
  }
  if (ending === 'stl') {
    const [one] = parts
    const material = new THREE.MeshStandardMaterial({ color: 0xb8b0a2, flatShading: true })
    const points = one.attributes.position?.array.length ?? 0
    if (one.index || points <= PIECE * 9) return new THREE.Mesh(geometry(one), material)
    const group = new THREE.Group()
    for (let at = 0; at < points; at += PIECE * 9) group.add(new THREE.Mesh(geometry(one, [at, at + PIECE * 9]), material))
    return group
  }
  // As OBJLoader makes them: the .mtl's own for a mesh, its colour for lines and points; else its defaults.
  const material = (kind: Part['kind'], said: Part['materials'][number]) => {
    const own = mtl?.create(said.name)
    if (own && kind === 'mesh') return own
    const made = kind === 'lines' ? new THREE.LineBasicMaterial() : kind === 'points' ? new THREE.PointsMaterial({ size: 1, sizeAttenuation: false }) : new THREE.MeshPhongMaterial()
    if (own) made.color.copy(own.color)
    else Object.assign(made, said)
    return made
  }
  const group = new THREE.Group()
  for (const one of parts) {
    const materials = one.materials.map(said => material(one.kind, said))
    const Kind = one.kind === 'lines' ? THREE.LineSegments : one.kind === 'points' ? THREE.Points : THREE.Mesh
    const object = new Kind(geometry(one), materials.length > 1 ? materials : materials[0])
    object.name = one.name
    group.add(object)
  }
  return group
}

/**
 * A model read from its address and parsed by its name; a string says why it is not drawn.
 * `onChange`: what it names beside it (an .mtl's textures, a 3MF's) came after it was given back.
 * shortcut: a glTF and a 3MF are parsed on the page's thread - a glTF's scene comes with its textures, and
 * three's 3MF reader needs DOMParser, which a worker has not; move them too if large ones hold the page.
 */
export async function load(src: string, name: string, { signal, onChange }: { signal?: AbortSignal; onChange?: () => void } = {}): Promise<Loaded | string> {
  const answer = await fetch(src, { signal }).catch(() => null)
  if (answer?.status === 413) return TOO_LARGE
  if (!answer?.ok) return 'It could not be read.'
  const data = await answer.arrayBuffer().catch(() => null) // (cut off when it is no longer wanted)
  if (!data) return 'It could not be read.'
  if (data.byteLength > MAX_BYTES) return TOO_LARGE
  const bytes = data.byteLength // (an STL's or OBJ's bytes are moved to the worker, not copied)
  const base = new URL('.', new URL(src, location.href)).href
  const manager = new THREE.LoadingManager()
  const check = guard(base)
  manager.setURLModifier(check)
  manager.onLoad = () => onChange?.()
  const ending = name.split('.').at(-1)?.toLowerCase()
  let object: THREE.Object3D
  let unit: string | null = null
  try {
    if (ending === 'stl' || ending === 'obj') {
      const parsed = await offThread(data, ending, signal)
      if (typeof parsed === 'string') return parsed
      const materials = parsed.mtl ? await new MTLLoader(manager).setPath(base).loadAsync(parsed.mtl).catch(() => null) : null
      materials?.preload()
      object = built(parsed, ending, materials)
    } else if (ending === 'gltf' || ending === 'glb') {
      const json = gltfJson(data)
      if (gltfTooLarge(json)) return TOO_LARGE_UNPACKED
      const beside = await besideOf(json, base, check, signal)
      if (typeof beside === 'string') return beside
      // Only what was read and counted, or what it carries in itself; anything else it asks for is refused.
      manager.setURLModifier((url: string) => beside.get(url) ?? (/^(data|blob):/i.test(url) ? url : REFUSED))
      try {
        object = (await new GLTFLoader(manager).parseAsync(data, base)).scene
      } finally {
        beside.forEach(url => URL.revokeObjectURL(url))
      }
      unit = 'm' // (glTF's own unit: metres)
    } else if (ending === '3mf') {
      // What it unpacks to, from its zip's own list, before anything is unpacked.
      let unpacked = 0
      unzipSync(new Uint8Array(data), { filter: (file: { originalSize: number }) => ((unpacked += file.originalSize), false) })
      if (unpacked > MAX_UNPACKED) return TOO_LARGE_UNPACKED
      object = new ThreeMFLoader(manager).parse(data)
      // shortcut: the zip is read twice (the loader keeps its unit to itself); upgrade if large 3MFs are slow.
      const [model] = Object.values(unzipSync(new Uint8Array(data), { filter: (file: { name: string }) => file.name.endsWith('.model') }))
      const said = model && /<model\b[^>]*\bunit\s*=\s*["'](\w+)["']/.exec(new TextDecoder().decode(model as Uint8Array))?.[1]
      unit = UNITS[said ?? 'millimeter'] ?? said // (the 3MF format's own default: millimetres)
    } else return UNREADABLE
  } catch {
    return UNREADABLE
  }
  if (!object) return UNREADABLE
  const count = triangles(object)
  if (count > MAX_TRIANGLES) {
    dispose(object)
    return tooMany(count)
  }
  // STL and 3MF stand on z, as CAD and slicers have them; the view stands on y.
  if (ending === 'stl' || ending === '3mf') object.rotation.x = -Math.PI / 2
  return { object, bytes, unit, triangles: count }
}

/** Its geometry, materials and textures let go of. */
export function dispose(object: THREE.Object3D) {
  object.traverse((part: THREE.Mesh) => {
    part.geometry?.dispose()
    for (const material of [part.material ?? []].flat()) {
      for (const value of Object.values(material) as THREE.Texture[]) if (value?.isTexture) value.dispose()
      material.dispose()
    }
  })
}
