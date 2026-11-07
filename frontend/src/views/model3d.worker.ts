// K-58: an STL or OBJ parsed off the page's thread (`model3d.ts` starts this): its bytes in, its arrays out, moved.
import { parse, transferOf } from './model3dParse'

self.onmessage = (event: MessageEvent<{ data: ArrayBuffer; ending: string }>) => {
  const parsed = parse(event.data.data, event.data.ending)
  self.postMessage(parsed, { transfer: transferOf(parsed) })
}
