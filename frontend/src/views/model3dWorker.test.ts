// K-58: an STL or OBJ is parsed in a worker - its bytes posted in, its arrays posted back moved - so a large one
// does not hold the page; a glTF's files beside it may come to 200 MB all together, and no more.
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { PIECE, load } from './model3d'
import { parse } from './model3dParse'

const STL = 'solid part\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 3 0\nendloop\nendfacet\nendsolid part\n'
const bytes = (text: string) => new TextEncoder().encode(text).buffer as ArrayBuffer
let answers: Record<string, () => Response | Partial<Response> | Promise<Response>> = {}
let asked: string[] = []
beforeEach(() => {
  answers = {}
  asked = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | Request) => {
      const at = typeof url === 'string' ? url : url.url
      asked.push(at)
      return answers[at]?.() ?? new Response('', { status: 404 })
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

test('an STL goes to the worker as its bytes, moved; what comes back is drawn, and the worker is let go', async () => {
  const made: { url: URL; options: WorkerOptions; posted: unknown[]; ended: boolean }[] = []
  vi.stubGlobal(
    'Worker',
    class {
      onmessage: ((event: { data: unknown }) => void) | null = null
      seen = { url: new URL('x:'), options: {}, posted: [] as unknown[], ended: false }
      constructor(url: URL, options: WorkerOptions) {
        Object.assign(this.seen, { url, options })
        made.push(this.seen)
      }
      postMessage(message: { data: ArrayBuffer; ending: string }, transfer: Transferable[]) {
        this.seen.posted = [message, transfer]
        setTimeout(() => this.onmessage?.({ data: parse(message.data, message.ending) }))
      }
      terminate() {
        this.seen.ended = true
      }
    },
  )
  answers['/m/part.stl'] = () => new Response(STL)
  const read = await load('/m/part.stl', 'part.stl')
  expect(typeof read !== 'string' && [read.triangles, read.bytes]).toEqual([1, STL.length])
  const [{ url, options, posted, ended }] = made
  expect([url.pathname.endsWith('/model3d.worker.ts'), options, ended]).toEqual([true, { type: 'module' }, true])
  const [message, transfer] = posted as [{ data: ArrayBuffer; ending: string }, ArrayBuffer[]]
  expect(message.ending).toBe('stl')
  expect(transfer).toEqual([message.data])
})

test('a worker that fails says the model could not be read, and is let go', async () => {
  const ended = vi.fn()
  vi.stubGlobal(
    'Worker',
    class {
      onerror: (() => void) | null = null
      postMessage() {
        setTimeout(() => this.onerror?.())
      }
      terminate = ended
    },
  )
  answers['/m/part.obj'] = () => new Response('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
  expect(await load('/m/part.obj', 'part.obj')).toBe('It could not be read as a 3D model.')
  expect(ended).toHaveBeenCalled()
})

test('the worker posts back the arrays of what it parsed, each buffer once, moved; an OBJ says the .mtl it names', async () => {
  const post = vi.spyOn(self, 'postMessage').mockImplementation(() => {})
  await import('./model3d.worker')
  self.onmessage?.(new MessageEvent('message', { data: { data: bytes('mtllib part.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl steel\nf 1 2 3\n'), ending: 'obj' } }))
  const [parsed, { transfer }] = post.mock.calls[0] as unknown as [Exclude<ReturnType<typeof parse>, string>, { transfer: ArrayBuffer[] }]
  expect(parsed.mtl).toBe('part.mtl')
  const [one] = parsed.parts
  expect([one.kind, one.materials.map(material => material.name)]).toEqual(['mesh', ['steel']])
  expect(transfer).toEqual([...new Set(Object.values(one.attributes).map(value => value.array.buffer))])
  expect(transfer.length).toBeGreaterThan(0)
  self.onmessage = null
})

test('a glTF whose files beside it come to over 200 MB is not parsed; under it, what was read is what it draws from', async () => {
  const parseGltf = vi.spyOn(GLTFLoader.prototype, 'parseAsync')
  const huge = () => ({ ok: true, blob: async () => ({ size: 150 * 1024 * 1024 }) as Blob })
  answers['http://localhost:3000/m/a.bin'] = huge
  answers['http://localhost:3000/m/b.bin'] = huge
  answers['/m/big.gltf'] = () => new Response(JSON.stringify({ asset: { version: '2.0' }, buffers: [{ uri: 'a.bin', byteLength: 1 }, { uri: 'b.bin', byteLength: 1 }] }))
  expect(await load('/m/big.gltf', 'big.gltf')).toBe('Too large to show here: the files beside it come to over 200 MB.')
  expect(parseGltf).not.toHaveBeenCalled()

  // (jsdom makes no blob addresses: here they answer with what was read)
  const revoked: string[] = []
  const was = { create: URL.createObjectURL, revoke: URL.revokeObjectURL }
  Object.assign(URL, {
    createObjectURL: (blob: Blob) => {
      const url = `blob:http://localhost:3000/${revoked.length}-read`
      answers[url] = async () => new Response(await blob.arrayBuffer()) // (jsdom's Blob is not this realm's Response's)
      return url
    },
    revokeObjectURL: (url: string) => revoked.push(url),
  })
  try {
    const triangle = new Float32Array([0, 0, 0, 4, 0, 0, 0, 5, 0])
    answers['http://localhost:3000/m/one.bin'] = () => new Response(triangle)
    answers['/m/one.gltf'] = () =>
      new Response(
        JSON.stringify({
          asset: { version: '2.0' },
          scenes: [{ nodes: [0] }],
          nodes: [{ mesh: 0 }],
          meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
          accessors: [{ bufferView: 0, count: 3, type: 'VEC3', componentType: 5126, min: [0, 0, 0], max: [4, 5, 0] }],
          bufferViews: [{ buffer: 0, byteLength: 36 }],
          buffers: [{ uri: 'one.bin', byteLength: 36 }],
        }),
      )
    asked = []
    const one = await load('/m/one.gltf', 'one.gltf')
    expect(typeof one !== 'string' && one.triangles).toBe(1)
    // read once, by the folder's own address; drawn from what was read, which is let go of after
    expect(asked).toEqual(['/m/one.gltf', 'http://localhost:3000/m/one.bin', 'blob:http://localhost:3000/0-read'])
    expect(revoked).toEqual(['blob:http://localhost:3000/0-read'])
  } finally {
    Object.assign(URL, { createObjectURL: was.create, revokeObjectURL: was.revoke })
  }
})

test('B-341: a large STL comes back without normals (drawn flat) and with its box, in pieces that share its one array', async () => {
  // A binary STL of PIECE + 1 triangles: an 80-byte header, the count, then 50 bytes each.
  const count = PIECE + 1
  const data = new ArrayBuffer(84 + 50 * count)
  const view = new DataView(data)
  view.setUint32(80, count, true)
  for (let n = 0; n < count; n++) for (let corner = 0; corner < 3; corner++) view.setFloat32(84 + 50 * n + 12 + 12 * corner, n + corner, true)
  const parsed = parse(data.slice(0), 'stl')
  expect(typeof parsed !== 'string' && [Object.keys(parsed.parts[0].attributes), parsed.parts[0].bounds?.max[0]]).toEqual([['position'], count + 1])
  answers['/m/big.stl'] = () => new Response(data)
  const read = await load('/m/big.stl', 'big.stl')
  if (typeof read === 'string') throw new Error(read)
  expect(read.triangles).toBe(count)
  const pieces = read.object.children as { geometry: { attributes: { position: { array: Float32Array } }; boundingBox: unknown } }[]
  expect(pieces.map(piece => piece.geometry.attributes.position.array.length)).toEqual([PIECE * 9, 9])
  expect(new Set(pieces.map(piece => piece.geometry.attributes.position.array.buffer)).size).toBe(1)
  expect(pieces.every(piece => piece.geometry.boundingBox)).toBe(true)
})
