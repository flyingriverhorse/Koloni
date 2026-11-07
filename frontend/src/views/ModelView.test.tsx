// Slice 58: a 3D model opens a 3D view in the Files window - loaded only then; what it names beside
// it is read from its own folder only; too large or too many triangles, it is not drawn; without
// WebGL (as in jsdom) it says so; the keys turn and zoom it.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as THREE from 'three'
import { strToU8 as encode, zipSync } from 'three/examples/jsm/libs/fflate.module.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { View } from '../api/types'
import { agent, fileChange } from '../test-fixtures'
import { FilesWindow } from './FilesWindow'
import { MAX_TRIANGLES, gltfTooLarge, guard, load, step, triangles } from './model3d'
import { kindOf } from './views'

const STL = 'solid part\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 3 0\nendloop\nendfacet\nendsolid part\n'
const realFetch = globalThis.fetch
let answers: Record<string, () => Response> = {}
let asked: string[] = []
beforeEach(() => {
  answers = {}
  asked = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | Request) => {
      const at = typeof url === 'string' ? url : url.url
      asked.push(at)
      if (at.startsWith('data:')) return realFetch(at) // (what a model carries in itself)
      return answers[at]?.() ?? new Response('[]', { status: at.includes('/files') ? 200 : 404 })
    }),
  )
  vi.spyOn(console, 'error') // (jsdom has no WebGL, and says so)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const model = (over: Partial<View> = {}): View => ({
  id: 'v1',
  path: 'parts/part.stl',
  kind: 'model',
  agent_id: 'r1',
  status: 'shown',
  sha: 'sha1',
  note: null,
  too_large: false,
  url: '/api/conversations/c1/views/v1/part.stl',
  at: '2026-10-20T10:00:00Z',
  ...over,
})
const window_ = (views: View[], more: Partial<Parameters<typeof FilesWindow>[0]> = {}) =>
  render(
    <FilesWindow
      project={{ id: 'p', root_path: 'C:/work/koloni' }}
      changes={[]}
      views={views}
      fresh={[]}
      agents={[agent('r1', 'running', { id: 'r1', name: 'Lead' })]}
      open
      at={{ key: views[0] ? views[0].path : null, n: 1 }}
      height={0.45}
      expanded={false}
      onExpand={() => {}}
      onClose={() => {}}
      onSeen={() => {}}
      onDecide={async () => {}}
      {...more}
    />,
  )

test('STL, OBJ, glTF, GLB and 3MF are models, by their name in any case; what a model names beside it is not', () => {
  expect(['a.stl', 'b.OBJ', 'c.gltf', 'd.glb', 'e.3mf'].map(kindOf)).toEqual(['model', 'model', 'model', 'model', 'model'])
  expect(['a.mtl', 'a.bin', 'a.step'].map(kindOf)).toEqual([null, null, null])
})

test('a model opens the 3D view, loaded only then; without WebGL it says so plainly, and nothing breaks', async () => {
  window_([model()])
  expect(await screen.findByText('This browser cannot draw 3D here.')).toBeInTheDocument()
  // (nothing of the model's bytes is read where it cannot be drawn - its history line, K-devir-4, reads none of them)
  expect(asked.filter(a => a.includes('part.stl') && /\/raw\/|\/file\?/.test(a))).toEqual([])
  expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Code' }))
  expect(screen.queryByText('This browser cannot draw 3D here.')).not.toBeInTheDocument()
})

test('a model an agent changed opens on the model, its diff a click away; one too large is not loaded', async () => {
  const change = fileChange('f1', 'r1', { path: 'parts/part.stl', kind: 'create', status: 'proposed', diff: '@@ -0,0 +1 @@\n+solid part\n' })
  const { unmount } = window_([model({ status: 'proposed' })], { changes: [change] })
  expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByText('This browser cannot draw 3D here.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Diff' }))
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  unmount()
  window_([model({ too_large: true, sha: null })])
  expect(screen.getByText('Too large to show: over 50 MB.')).toBeInTheDocument()
})

test('what a model names beside it comes from its own folder of this origin only, or from itself', () => {
  const beside = guard('http://app/api/projects/p/raw/parts/')
  expect(beside('part.bin')).toBe('http://app/api/projects/p/raw/parts/part.bin')
  expect(beside('http://app/api/projects/p/raw/parts/tex/a.png')).toBe('http://app/api/projects/p/raw/parts/tex/a.png')
  expect(beside('data:application/octet-stream;base64,AAAA')).toBe('data:application/octet-stream;base64,AAAA')
  expect(beside('blob:http://app/1234')).toBe('blob:http://app/1234')
  for (const away of ['../secret.bin', '%2e%2e/secret.bin', '/api/conversations', 'http://elsewhere/a.png', '//elsewhere/a.png', 'file:///C:/a.png', 'part.bin?again=1', 'part.bin#again', 'sub%2f..%2f..%2fsecret.bin', 'sub%5Csecret.bin'])
    expect(beside(away), away).toBe('about:blank')
  // no more than 32 files beside it, each of which may be as large as itself; the same one again is not another
  const fresh = guard('http://app/m/')
  for (let n = 1; n <= 32; n++) expect(fresh(`b${n}.bin`)).toBe(`http://app/m/b${n}.bin`)
  expect(fresh('b1.bin')).toBe('http://app/m/b1.bin')
  expect(fresh('b33.bin')).toBe('about:blank')
})

test('a model is read from its address and parsed by its name: its triangles and size counted; too large is not drawn', async () => {
  answers['/m/part.stl'] = () => new Response(STL)
  const read = await load('/m/part.stl', 'part.stl')
  expect(typeof read).toBe('object')
  if (typeof read === 'string') return
  expect([read.triangles, read.bytes, read.unit]).toEqual([1, STL.length, null])
  answers['/m/big.glb'] = () => new Response('', { status: 413 })
  expect(await load('/m/big.glb', 'big.glb')).toBe('Too large to draw: over 50 MB.')
  answers['/m/bad.glb'] = () => new Response('not a model')
  expect(await load('/m/bad.glb', 'bad.glb')).toBe('It could not be read as a 3D model.')
})

test('an OBJ reads the .mtl it names from beside it; one it names elsewhere is not asked for', async () => {
  answers['http://localhost:3000/m/part.mtl'] = () => new Response('newmtl steel\nKd 0.5 0.5 0.5\n')
  answers['/m/part.obj'] = () => new Response('mtllib part.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl steel\nf 1 2 3\n')
  const read = await load('/m/part.obj', 'part.obj')
  expect(typeof read !== 'string' && read.triangles).toBe(1)
  expect(asked).toContain('http://localhost:3000/m/part.mtl')
  answers['/m/far.obj'] = () => new Response('mtllib ../../far.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
  asked = []
  expect(typeof (await load('/m/far.obj', 'far.obj'))).toBe('object')
  expect(asked.filter(a => a.includes('far.mtl'))).toEqual([])
})

test('a 3MF says its unit - millimetres where it says none, as the format has it', async () => {
  // (copied into this realm's Uint8Array: jsdom's TextEncoder gives one fflate does not take for bytes)
  const strToU8 = (text: string) => new Uint8Array(encode(text))
  const threeMF = (unit: string) =>
    zipSync({
      '[Content_Types].xml': strToU8('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'),
      '_rels/.rels': strToU8('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="r0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'),
      '3D/3dmodel.model': strToU8(
        `<?xml version="1.0"?><model ${unit} xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources><build><item objectid="1"/></build></model>`,
      ),
    })
  answers['/m/inch.3mf'] = () => new Response(threeMF('unit="inch"'))
  answers['/m/plain.3mf'] = () => new Response(threeMF(''))
  const inch = await load('/m/inch.3mf', 'inch.3mf')
  const plain = await load('/m/plain.3mf', 'plain.3mf')
  expect([typeof inch !== 'string' && inch.unit, typeof inch !== 'string' && inch.triangles]).toEqual(['in', 1])
  expect(typeof plain !== 'string' && plain.unit).toBe('mm')
})

test('over two million triangles, a model is not drawn: the note says how many', async () => {
  const huge = new THREE.BufferGeometry()
  huge.setIndex(new THREE.BufferAttribute(new Uint8Array(3 * (MAX_TRIANGLES + 1)), 1))
  expect(triangles(new THREE.Mesh(huge))).toBe(MAX_TRIANGLES + 1)
  vi.spyOn(STLLoader.prototype, 'parse').mockReturnValue(huge)
  answers['/m/dense.stl'] = () => new Response(STL)
  expect(await load('/m/dense.stl', 'dense.stl')).toMatch(/^Too many triangles to draw: 2,000,001, over 2,000,000\.$/)
})

test('a 3MF that would unpack to more than 200 MB - as its zip says - is refused before anything is unpacked', async () => {
  const zip = zipSync({ '3D/3dmodel.model': new Uint8Array(encode('<model/>')), '_rels/.rels': new Uint8Array(encode('<r/>')) })
  // (its central directory says each file is 2 GB)
  const view = new DataView(zip.buffer)
  for (let at = 0; at < zip.length - 4; at++) if (view.getUint32(at, true) === 0x02014b50) view.setUint32(at + 24, 0x7fffffff, true)
  const parse = vi.spyOn(ThreeMFLoader.prototype, 'parse')
  answers['/m/bomb.3mf'] = () => new Response(zip)
  expect(await load('/m/bomb.3mf', 'bomb.3mf')).toBe('Too large to draw: it unpacks to over 200 MB.')
  expect(parse).not.toHaveBeenCalled()
})

test('an OBJ of over two million triangles is counted before it is parsed, and not parsed', async () => {
  const parse = vi.spyOn(OBJLoader.prototype, 'parse')
  answers['/m/dense.obj'] = () => new Response(`v 0 0 0\nf ${'1 '.repeat(MAX_TRIANGLES + 3)}\n`)
  expect(await load('/m/dense.obj', 'dense.obj')).toBe('Too many triangles to draw: 2,000,001, over 2,000,000.')
  expect(parse).not.toHaveBeenCalled()
})

test('a glTF whose arrays its JSON alone makes - or that would be too large - is refused before it is parsed; one drawn is in metres', async () => {
  const accessor = { bufferView: 0, count: 3, type: 'VEC3', componentType: 5126 }
  expect(gltfTooLarge({ accessors: [accessor] })).toBe(false)
  expect(gltfTooLarge({ accessors: [{ ...accessor, bufferView: undefined }] })).toBe(true)
  expect(gltfTooLarge({ accessors: [{ ...accessor, count: -1 }] })).toBe(true)
  expect(gltfTooLarge({ accessors: [{ ...accessor, bufferView: undefined, sparse: {}, count: 20_000_000 }] })).toBe(true)
  const parse = vi.spyOn(GLTFLoader.prototype, 'parseAsync')
  answers['/m/empty.gltf'] = () => new Response(JSON.stringify({ asset: { version: '2.0' }, accessors: [{ count: 1e9, type: 'MAT4', componentType: 5126 }] }))
  expect(await load('/m/empty.gltf', 'empty.gltf')).toBe('Too large to draw: it unpacks to over 200 MB.')
  expect(parse).not.toHaveBeenCalled()
  const bytes = new Uint8Array(new Float32Array([0, 0, 0, 4, 0, 0, 0, 5, 0]).buffer)
  const gltf = {
    asset: { version: '2.0' },
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    accessors: [{ ...accessor, min: [0, 0, 0], max: [4, 5, 0] }],
    bufferViews: [{ buffer: 0, byteLength: 36 }],
    buffers: [{ byteLength: 36, uri: `data:application/octet-stream;base64,${btoa(String.fromCharCode(...bytes))}` }],
  }
  answers['/m/one.gltf'] = () => new Response(JSON.stringify(gltf))
  const one = await load('/m/one.gltf', 'one.gltf')
  expect(typeof one !== 'string' && [one.unit, one.triangles]).toEqual(['m', 1])
})

test('instances count: a mesh drawn five times is five times its triangles', () => {
  const one = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(9), 3))
  expect(triangles(new THREE.InstancedMesh(one, new THREE.MeshBasicMaterial(), 5))).toBe(5)
})

test('a texture that comes after the model is given back is drawn as it comes: onChange', async () => {
  const textures: string[] = []
  vi.spyOn(THREE.ImageLoader.prototype, 'load').mockImplementation(function (this: { manager: THREE.LoadingManager }, url: string, onLoad: (image: unknown) => void) {
    const image = document.createElement('img')
    textures.push(url)
    this.manager.itemStart(url)
    setTimeout(() => {
      onLoad(image)
      this.manager.itemEnd(url)
    }, 20)
    return image
  })
  answers['http://localhost:3000/m/skin.mtl'] = () => new Response('newmtl steel\nmap_Kd skin.png\n')
  answers['/m/skin.obj'] = () => new Response('mtllib skin.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl steel\nf 1 2 3\n')
  const onChange = vi.fn()
  const read = await load('/m/skin.obj', 'skin.obj', { onChange })
  expect(typeof read).toBe('object')
  const before = onChange.mock.calls.length
  expect(textures).toEqual(['http://localhost:3000/m/skin.png'])
  await vi.waitFor(() => expect(onChange.mock.calls.length).toBeGreaterThan(before))
})

test('the arrow keys turn the view around what it looks at, a step each; + and - zoom; other keys are not the view’s', () => {
  const from = new THREE.Vector3(0, 0, 10)
  const left = step('ArrowLeft', from)!
  expect(left.length()).toBeCloseTo(10)
  expect(left.angleTo(from)).toBeCloseTo(Math.PI / 18)
  expect(step('ArrowRight', left)!.distanceTo(from)).toBeCloseTo(0)
  expect(step('ArrowUp', from)!.y).toBeGreaterThan(0)
  expect(step('+', from)!.length()).toBeCloseTo(8)
  expect(step('-', from)!.length()).toBeCloseTo(12.5)
  expect(step('−', from)!.length()).toBeCloseTo(12.5)
  expect(step('a', from)).toBeNull()
  // (never over the top: it would turn upside down)
  let up = from
  for (let n = 0; n < 40; n++) up = step('ArrowUp', up)!
  expect(up.y).toBeLessThanOrEqual(10)
  expect(up.length()).toBeCloseTo(10)
})
