// Slice 58's sample models, made here rather than kept as files: a box as an ASCII STL, and one
// triangle as a GLB (glTF's binary form: a header, its JSON, its buffer).

/** A box x by y by z from the origin: twelve triangles. */
export function boxStl(x, y, z) {
  const v = [[0, 0, 0], [x, 0, 0], [x, y, 0], [0, y, 0], [0, 0, z], [x, 0, z], [x, y, z], [0, y, z]]
  const faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
  const facet = f => `facet normal 0 0 0\nouter loop\n${f.map(i => `vertex ${v[i].join(' ')}`).join('\n')}\nendloop\nendfacet`
  return `solid box\n${faces.map(facet).join('\n')}\nendsolid box\n`
}

/** One triangle, 4 wide and 5 high. */
export function triangleGlb() {
  const bin = Buffer.from(new Float32Array([0, 0, 0, 4, 0, 0, 0, 5, 0]).buffer)
  const gltf = {
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [4, 5, 0] }],
    bufferViews: [{ buffer: 0, byteLength: bin.length }],
    buffers: [{ byteLength: bin.length }],
  }
  let json = Buffer.from(JSON.stringify(gltf))
  json = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 0x20)])
  const chunk = (data, type) => {
    const head = Buffer.alloc(8)
    head.writeUInt32LE(data.length, 0)
    head.writeUInt32LE(type, 4)
    return Buffer.concat([head, data])
  }
  const body = Buffer.concat([chunk(json, 0x4e4f534a), chunk(bin, 0x004e4942)])
  const head = Buffer.alloc(12)
  head.writeUInt32LE(0x46546c67, 0)
  head.writeUInt32LE(2, 4)
  head.writeUInt32LE(12 + body.length, 8)
  return Buffer.concat([head, body])
}
