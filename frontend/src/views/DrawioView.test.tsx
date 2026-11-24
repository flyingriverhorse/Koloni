// K-drawio: a .drawio file opens on the vendored viewer in a sandboxed frame; the app hands the frame a port of its own
// once it is there, posts the file's text in by it, hears only what comes back by it, and writes the picture it draws
// beside the diagram (Save as PNG / SVG).
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DrawioView } from './DrawioView'
import { kindOf } from './views'

const XML = '<mxfile><diagram name="P"><mxGraphModel><root/></mxGraphModel></diagram></mxfile>'
const PNG = { saved: 'png', data: 'data:image/png;base64,QUJD' }
const ports: MessagePort[] = []
beforeEach(() =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(XML)),
  ),
)
afterEach(() => {
  ports.splice(0).forEach(port => port.close())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** The frame, loaded: the port it was handed - the frame's end of it - and what the app posts in by it. */
async function opened() {
  render(<DrawioView src="/api/projects/p1/raw/docs/flow.drawio" path="docs/flow.drawio" projectId="p1" />)
  const frame = screen.getByTitle('Diagram docs/flow.drawio') as HTMLIFrameElement
  const posted = vi.spyOn(frame.contentWindow!, 'postMessage')
  act(() => frame.dispatchEvent(new Event('load')))
  // The one post into the frame, to '*' (it is of no origin): its port, with nothing of the file.
  expect(posted).toHaveBeenCalledTimes(1)
  const [hello, target, transfer] = posted.mock.calls[0] as unknown as [string, string, MessagePort[]]
  expect([hello, target]).toEqual(['koloni', '*'])
  const port = transfer[0]
  ports.push(port)
  const got: unknown[] = []
  port.onmessage = event => got.push(event.data)
  await waitFor(() => expect(got).toEqual([{ xml: XML }]))
  /** What the frame says, then a line it says after it: heard in order, so once that shows, the first was heard. */
  const say = async (data: unknown) => {
    port.postMessage(data)
    port.postMessage({ failed: 'said' })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('said'))
  }
  return { frame, posted, port, got, say }
}

test('a draw.io file by any of its names is a diagram', () => {
  expect(['a.drawio', 'b/C.DRAWIO.XML', 'd.dio'].map(kindOf)).toEqual(['drawio', 'drawio', 'drawio'])
  expect(kindOf('e.xml')).toBe(null)
})

test('the viewer is framed sandboxed, with scripts and no same origin; the file is posted in by its port', async () => {
  const { frame } = await opened()
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
  expect(frame).toHaveAttribute('src', '/drawio/viewer.html')
})

test('Save as PNG asks the frame, and what it draws is written beside the diagram; nothing on the window is heard', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.png' })
  const { frame, posted, port, got, say } = await opened()
  const png = screen.getByRole('button', { name: 'Save as PNG' })
  expect(png).toBeDisabled()
  port.postMessage({ shown: true })
  await waitFor(() => expect(png).toBeEnabled())
  await userEvent.click(png)
  await waitFor(() => expect(got).toContainEqual({ save: 'png' }))
  expect(posted).toHaveBeenCalledTimes(1) // (by the port, never to '*' again)
  // Not what comes to the window - from another window, nor from its own frame: the frame is heard by its port alone.
  for (const source of [window, frame.contentWindow])
    act(() => window.dispatchEvent(new MessageEvent('message', { data: PNG, source, origin: 'null' })))
  expect(written).not.toHaveBeenCalled()
  port.postMessage(PNG)
  await waitFor(() =>
    expect(written).toHaveBeenCalledWith('/projects/p1/diagram-picture', {
      path: 'docs/flow.drawio',
      format: 'png',
      data: 'QUJD',
    }),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Saved as docs/flow.png.')
  // once: the same answer again, unasked, writes nothing
  await say(PNG)
  expect(written).toHaveBeenCalledTimes(1)
})

test('a picture the frame sends unasked - or of another format than asked - is not written', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.png' })
  const { port, say } = await opened()
  port.postMessage({ shown: true })
  await say(PNG)
  await userEvent.click(screen.getByRole('button', { name: 'Save as SVG' }))
  await say(PNG)
  expect(written).not.toHaveBeenCalled()
})

test('an SVG goes as its UTF-8 bytes, and why the frame could not draw is said', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.svg' })
  const { port } = await opened()
  port.postMessage({ shown: true })
  const svg = screen.getByRole('button', { name: 'Save as SVG' })
  await waitFor(() => expect(svg).toBeEnabled())
  await userEvent.click(svg)
  port.postMessage({ saved: 'svg', data: '<svg>ş</svg>' })
  await waitFor(() =>
    expect(written).toHaveBeenCalledWith('/projects/p1/diagram-picture', {
      path: 'docs/flow.drawio',
      format: 'svg',
      data: btoa('<svg>\xc5\x9f</svg>'),
    }),
  )
  expect(await screen.findByText('Saved as docs/flow.svg.')).toBeInTheDocument()
  port.postMessage({ failed: 'This is not a draw.io file: its XML could not be read.' })
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('its XML could not be read'))
})

test('a frame that loads again went elsewhere: taken off, and nothing more is posted into it', async () => {
  const { frame, posted } = await opened()
  act(() => frame.dispatchEvent(new Event('load')))
  expect(screen.getByText('The diagram tried to go elsewhere; it was stopped.')).toBeInTheDocument()
  expect(posted).toHaveBeenCalledTimes(1)
})
