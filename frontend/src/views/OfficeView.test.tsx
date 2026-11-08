import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { utils, write } from 'xlsx'
import { OfficeView } from './OfficeView'
import { MOST_ROWS, draw, listen } from './office/viewer'

// K-belge-ciktilari: the app reads the file and posts its bytes into the document viewer's frame of no origin, once it
// has loaded; it hears that frame alone; a frame that loads again went elsewhere and is taken off.

afterEach(() => vi.unstubAllGlobals())

const bytes = new Uint8Array([80, 75, 3, 4]).buffer
const answer = (status: number) => vi.fn(async () => new Response(status === 200 ? bytes : null, { status }))

test('the bytes go to its own frame once both are there; only that frame is heard', async () => {
  vi.stubGlobal('fetch', answer(200))
  localStorage.setItem('koloni-key', 'the-key')
  render(<OfficeView src="/api/x/plan.docx" path="plan.docx" kind="docx" />)
  const frame = screen.getByTitle('Document plan.docx') as HTMLIFrameElement
  const posted = vi.spyOn(frame.contentWindow!, 'postMessage')
  fireEvent.load(frame)
  await waitFor(() => expect(posted).toHaveBeenCalledWith({ kind: 'docx', data: expect.any(ArrayBuffer) }, '*'))
  // (Read with the page's key, as the server asks of a document on its keyless door.)
  expect(fetch).toHaveBeenCalledWith('/api/x/plan.docx', { headers: { 'X-KOLONI-Key': 'the-key' } })
  // Another window's word is not taken for the frame's.
  act(() => window.dispatchEvent(new MessageEvent('message', { data: { failed: 'from elsewhere' }, source: window, origin: 'null' })))
  // Nor its own frame's window with an origin: the sandboxed viewer is of none.
  act(() => window.dispatchEvent(new MessageEvent('message', { data: { failed: 'from elsewhere' }, source: frame.contentWindow, origin: location.origin })))
  expect(screen.queryByText(/from elsewhere/)).toBeNull()
  act(() => window.dispatchEvent(new MessageEvent('message', { data: { failed: 'not a zip' }, source: frame.contentWindow, origin: 'null' })))
  expect(screen.getByRole('status')).toHaveTextContent('It could not be drawn: not a zip')
  // A second load: it went elsewhere by itself.
  fireEvent.load(frame)
  expect(screen.getByText('The document tried to go elsewhere; it was stopped.')).toBeInTheDocument()
})

test('one over the size the server serves says so, and nothing is posted', async () => {
  vi.stubGlobal('fetch', answer(413))
  render(<OfficeView src="/api/x/big.xlsx" path="big.xlsx" kind="xlsx" />)
  expect(await screen.findByRole('status')).toHaveTextContent('Too large to show: over 5 MB.')
})

test('a workbook is drawn sheet by sheet, its text as text, and a long one only to its first rows', async () => {
  const book = utils.book_new()
  utils.book_append_sheet(book, utils.aoa_to_sheet([['name', 'total'], ['<b>bold</b>', 3]]), 'Sums')
  utils.book_append_sheet(book, utils.aoa_to_sheet(Array.from({ length: MOST_ROWS + 5 }, (_, i) => [i])), 'Long')
  const into = document.createElement('main')
  await draw({ kind: 'xlsx', data: write(book, { type: 'array', bookType: 'xlsx' }) }, into)
  expect(Array.from(into.querySelectorAll('h2'), h => h.textContent)).toEqual(['Sums', 'Long'])
  expect(into.querySelector('.sheet td')?.textContent).toBe('name')
  expect(into.querySelector('b')).toBeNull()
  expect(into.textContent).toContain('<b>bold</b>')
  expect(into.querySelector('.sheet-more')?.textContent).toBe(`Only its first ${MOST_ROWS} rows are shown.`)
})

test('the viewer hears its parent only from the origin it is served from, and answers to that origin alone', async () => {
  // (In jsdom the page is its own parent.)
  const told = vi.spyOn(window, 'postMessage').mockImplementation(() => {})
  const into = document.createElement('main')
  listen(into)
  const book = utils.book_new()
  utils.book_append_sheet(book, utils.aoa_to_sheet([['name']]), 'Sums')
  const asked = { kind: 'xlsx', data: write(book, { type: 'array', bookType: 'xlsx' }) }
  window.dispatchEvent(new MessageEvent('message', { data: asked, source: window, origin: 'https://elsewhere.example' }))
  window.dispatchEvent(new MessageEvent('message', { data: asked, source: window, origin: location.origin }))
  await waitFor(() => expect(told).toHaveBeenCalledWith({ shown: true }, location.origin))
  expect(told).toHaveBeenCalledTimes(1)
  told.mockRestore()
})
