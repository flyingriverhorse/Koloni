// K-drawio: a .drawio file opens on the vendored viewer in a sandboxed frame; the app posts the file's text in once the
// frame is there, hears only its own frame, and writes the picture it draws beside the diagram (Save as PNG / SVG).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DrawioView } from './DrawioView'
import { kindOf } from './views'

const XML = '<mxfile><diagram name="P"><mxGraphModel><root/></mxGraphModel></diagram></mxfile>'
beforeEach(() => vi.stubGlobal('fetch', vi.fn(async () => new Response(XML))))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** The frame, loaded, with what the app posts into it caught. */
async function opened() {
  render(<DrawioView src="/api/projects/p1/raw/docs/flow.drawio" path="docs/flow.drawio" projectId="p1" />)
  const frame = screen.getByTitle('Diagram docs/flow.drawio') as HTMLIFrameElement
  const posted = vi.spyOn(frame.contentWindow!, 'postMessage')
  act(() => frame.dispatchEvent(new Event('load')))
  await vi.waitFor(() => expect(posted).toHaveBeenCalledWith({ xml: XML }, '*'))
  // (The sandboxed frame is of no origin: its messages come from 'null'.)
  const say = (data: unknown, source: Window | null = frame.contentWindow, origin = 'null') =>
    act(() => window.dispatchEvent(new MessageEvent('message', { data, source, origin })))
  return { frame, posted, say }
}

test('a draw.io file by any of its names is a diagram', () => {
  expect(['a.drawio', 'b/C.DRAWIO.XML', 'd.dio'].map(kindOf)).toEqual(['drawio', 'drawio', 'drawio'])
  expect(kindOf('e.xml')).toBe(null)
})

test('the viewer is framed sandboxed, with scripts and no same origin; the file is posted in once it is there', async () => {
  const { frame } = await opened()
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
  expect(frame).toHaveAttribute('src', '/drawio/viewer.html')
})

test('Save as PNG asks the frame, and what it draws is written beside the diagram; another window is not heard', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.png' })
  const { frame, posted, say } = await opened()
  const png = screen.getByRole('button', { name: 'Save as PNG' })
  expect(png).toBeDisabled()
  say({ shown: true })
  expect(png).toBeEnabled()
  await userEvent.click(png)
  expect(posted).toHaveBeenCalledWith({ save: 'png' }, '*')
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' }, window)
  // Nor its own frame's window with an origin: that is not the sandboxed viewer.
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' }, frame.contentWindow, location.origin)
  expect(written).not.toHaveBeenCalled()
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' })
  expect(written).toHaveBeenCalledWith('/projects/p1/diagram-picture', { path: 'docs/flow.drawio', format: 'png', data: 'QUJD' })
  expect(await screen.findByRole('status')).toHaveTextContent('Saved as docs/flow.png.')
  // once: the same answer again, unasked, writes nothing
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' })
  expect(written).toHaveBeenCalledTimes(1)
})

test('a picture the frame sends unasked - or of another format than asked - is not written', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.png' })
  const { say } = await opened()
  say({ shown: true })
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' })
  await userEvent.click(screen.getByRole('button', { name: 'Save as SVG' }))
  say({ saved: 'png', data: 'data:image/png;base64,QUJD' })
  expect(written).not.toHaveBeenCalled()
})

test('an SVG goes as its UTF-8 bytes, and why the frame could not draw is said', async () => {
  const written = vi.spyOn(api, 'post').mockResolvedValue({ path: 'docs/flow.svg' })
  const { say } = await opened()
  say({ shown: true })
  await userEvent.click(screen.getByRole('button', { name: 'Save as SVG' }))
  say({ saved: 'svg', data: '<svg>ş</svg>' })
  expect(written).toHaveBeenCalledWith('/projects/p1/diagram-picture', { path: 'docs/flow.drawio', format: 'svg', data: btoa('<svg>\xc5\x9f</svg>') })
  expect(await screen.findByText('Saved as docs/flow.svg.')).toBeInTheDocument()
  say({ failed: 'This is not a draw.io file: its XML could not be read.' })
  expect(screen.getByRole('status')).toHaveTextContent('its XML could not be read')
})
