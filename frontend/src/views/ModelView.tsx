/**
 * A 3D model an agent made, in the Files window (slice 58): an STL, OBJ (with the .mtl it names),
 * glTF / GLB or 3MF, drawn with three.js - loaded only when a model opens (`FilesWindow` imports
 * this lazily). Turned, moved and zoomed by the mouse, turned and zoomed by the keyboard; Fit,
 * Reset view, Wireframe; its size and bounding box said in words. What it names beside it is read
 * from its own folder and nowhere else; nothing comes from the network.
 */
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { type Loaded, dispose, load, step } from './model3d'

const NO_WEBGL = 'This browser cannot draw 3D here.'
const LOST = 'The browser took the 3D view back (its graphics were lost): open the file again to draw it.'
const HOME = new THREE.Vector3(1, 0.8, 1).normalize()

const round = (n: number) => String(Math.round(n * 1000) / 1000)
const kilobytes = (bytes: number) => (bytes < 1024 * 1024 ? `${round(bytes / 1024)} KB` : `${round(bytes / 1024 / 1024)} MB`)

interface World {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  model: THREE.Object3D | null
  grid: THREE.GridHelper | null
  /** Laid out: its shape known. */
  sized: boolean
  /** Framed once: drawn anew, it is seen from where it was. */
  framed: boolean
  draw(): void
}

/** The model at `src` (a file's address in the app), named `name`; drawn anew when `src` changes, seen from where it was. */
export default function ModelView({ src, name }: { src: string; name: string }) {
  const host = useRef<HTMLDivElement>(null)
  const world = useRef<World | null>(null)
  const [ready, setReady] = useState(false)
  // Why nothing can be drawn here at all.
  const [cannot, setCannot] = useState<string | null>(null)
  const [shown, setShown] = useState<Omit<Loaded, 'object'> & { size: THREE.Vector3 } | string | null>(null)
  const [wire, setWire] = useState(false)

  useEffect(() => {
    const at = host.current
    if (!at) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    } catch {
      setCannot(NO_WEBGL)
      return
    }
    const lost = () => setCannot(LOST)
    renderer.domElement.addEventListener('webglcontextlost', lost)
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setClearColor(0x000000, 0) // (the ground is the theme's: the box's background, base.css)
    at.appendChild(renderer.domElement)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000)
    camera.add(new THREE.DirectionalLight(0xffffff, 2)) // lit from where it is seen
    scene.add(camera, new THREE.HemisphereLight(0xffffff, 0x666666, 1.5))
    const controls = new OrbitControls(camera, renderer.domElement)
    const draw = () => renderer.render(scene, camera)
    controls.addEventListener('change', draw)
    const w: World = { renderer, scene, camera, controls, model: null, grid: null, sized: false, framed: false, draw }
    world.current = w
    const fill = () => {
      if (!at.clientWidth || !at.clientHeight) return // (not laid out yet: the first fit waits for its shape)
      renderer.setSize(at.clientWidth, at.clientHeight, false)
      camera.aspect = at.clientWidth / at.clientHeight
      camera.updateProjectionMatrix()
      w.sized = true
      firstFit(w)
      draw()
    }
    fill()
    const resize = new ResizeObserver(fill)
    resize.observe(at)
    // The grid in the theme's colours, again when the theme changes.
    const theme = new MutationObserver(() => regrid(w))
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    setReady(true)
    return () => {
      resize.disconnect()
      theme.disconnect()
      controls.dispose()
      if (w.model) dispose(w.model)
      w.grid?.dispose()
      renderer.domElement.removeEventListener('webglcontextlost', lost)
      // (its GPU memory given back now, not when the browser gets round to it)
      renderer.forceContextLoss()
      renderer.dispose()
      renderer.domElement.remove()
      world.current = null
    }
  }, [])

  useEffect(() => {
    if (!ready) return
    let gone = false
    const stop = new AbortController()
    // (a texture beside it that comes later is drawn as it comes)
    const onChange = () => !gone && world.current?.draw()
    let ending = () => {}
    void load(src, name, { signal: stop.signal, onChange }).then(loaded => {
      const w = world.current
      if (gone || !w) {
        if (typeof loaded !== 'string') dispose(loaded.object)
        return
      }
      if (w.model) {
        w.scene.remove(w.model)
        dispose(w.model)
        w.model = null
      }
      if (typeof loaded === 'string') {
        setShown(loaded)
        return
      }
      const { object, ...said } = loaded
      // (measured in the file's own axes, before it is stood up)
      const turned = object.rotation.x
      object.rotation.x = 0
      const size = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3())
      object.rotation.x = turned
      w.model = object
      w.scene.add(object)
      // B-341: a large STL's pieces are drawn one a frame - a piece's first draw sends its arrays to the GPU,
      // and all at once held the page 1.9 s.
      const later = object.children.slice(1)
      for (const piece of later) piece.visible = false
      const next = () => {
        const piece = later.shift()
        if (gone || !piece) return
        piece.visible = true
        w.draw()
        showing = requestAnimationFrame(next)
      }
      let showing = requestAnimationFrame(next)
      ending = () => cancelAnimationFrame(showing)
      regrid(w)
      firstFit(w)
      setShown({ ...said, size })
      w.draw()
    })
    return () => {
      gone = true
      stop.abort()
      ending()
    }
  }, [ready, src, name])

  useEffect(() => {
    const w = world.current
    w?.model?.traverse((part: THREE.Mesh) => {
      for (const material of [part.material ?? []].flat()) if ('wireframe' in material) material.wireframe = wire
    })
    w?.draw()
  }, [wire, shown])

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const w = world.current
    if (!w) return
    const next = step(event.key, w.camera.position.clone().sub(w.controls.target))
    if (!next) return
    event.preventDefault()
    w.camera.position.copy(w.controls.target).add(next)
    w.controls.update()
    w.draw()
  }

  if (cannot) return <p className="view-empty muted">{cannot}</p>
  const drawn = shown !== null && typeof shown !== 'string'
  const unit = drawn && shown.unit ? ` ${shown.unit}` : ''
  return (
    <figure
      className="model-view"
      aria-label={name}
      // (a figure the keyboard turns: it takes the focus)
      tabIndex={0}
      aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Plus Minus"
      title="Drag to turn, right-drag to move, wheel to zoom; arrow keys turn, + and - zoom"
      onKeyDown={onKeyDown}
    >
      <div className="model-tools" role="group" aria-label="View">
        <button type="button" className="view-run" disabled={!drawn} onClick={() => world.current && frame(world.current, world.current.camera.position.clone().sub(world.current.controls.target))}>
          Fit
        </button>
        <button type="button" className="view-run" disabled={!drawn} onClick={() => world.current && frame(world.current, HOME)}>
          Reset view
        </button>
        <button type="button" className="view-run" disabled={!drawn} aria-pressed={wire} onClick={() => setWire(!wire)}>
          Wireframe
        </button>
      </div>
      <div ref={host} className="model-canvas" hidden={typeof shown === 'string'} />
      {typeof shown === 'string' && <p className="view-empty muted">{shown}</p>}
      <figcaption className="mono muted">
        {drawn
          ? `${kilobytes(shown.bytes)} · ${[shown.size.x, shown.size.y, shown.size.z].map(round).join(' × ')}${unit} · ${shown.triangles.toLocaleString()} ${shown.triangles === 1 ? 'triangle' : 'triangles'}`
          : typeof shown === 'string'
            ? 'Not drawn.'
            : 'Reading the model…'}
      </figcaption>
    </figure>
  )
}

/** The camera on the whole model, seen from `direction`. */
function frame(w: World, direction: THREE.Vector3) {
  if (!w.model) return
  const sphere = new THREE.Box3().setFromObject(w.model).getBoundingSphere(new THREE.Sphere())
  const radius = sphere.radius || 1
  const tall = (w.camera.fov * Math.PI) / 360
  const half = Math.min(tall, Math.atan(Math.tan(tall) * w.camera.aspect)) // (the narrower of its two angles)
  const distance = (radius / Math.sin(half)) * 1.1
  w.camera.position.copy(sphere.center).addScaledVector(direction.clone().normalize(), distance)
  w.camera.near = distance / 100
  w.camera.far = distance * 100
  w.camera.updateProjectionMatrix()
  w.controls.target.copy(sphere.center)
  w.controls.update()
  w.draw()
}

/** Seen whole from the start, once there is a model and the box's shape is known. */
function firstFit(w: World) {
  if (w.framed || !w.model || !w.sized) return
  w.framed = true
  frame(w, HOME)
}

/** A floor grid under the model, as wide as twice it, in the theme's colours. */
function regrid(w: World) {
  if (w.grid) {
    w.scene.remove(w.grid)
    w.grid.dispose()
    w.grid = null
  }
  if (!w.model) return
  const box = new THREE.Box3().setFromObject(w.model)
  const size = box.getSize(new THREE.Vector3())
  const look = getComputedStyle(w.renderer.domElement)
  const colour = (token: string) => new THREE.Color(look.getPropertyValue(token).trim() || '#888')
  w.grid = new THREE.GridHelper(2 * Math.max(size.x, size.z) || 1, 10, colour('--border-strong'), colour('--border'))
  w.grid.position.set((box.min.x + box.max.x) / 2, box.min.y, (box.min.z + box.max.z) / 2)
  w.scene.add(w.grid)
  w.draw()
}
