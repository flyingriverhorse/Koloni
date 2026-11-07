import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from '../App'
import { api, download, keyRefused, takeKey, withKey } from './client'

afterEach(() => vi.unstubAllGlobals())

test('the key the link opened the page with is kept, taken out of the address and carried by every request', async () => {
  history.replaceState(null, '', '/?x=1#key=k1')
  await takeKey()
  expect(location.hash).toBe('')
  expect(location.search).toBe('?x=1')
  expect(localStorage.getItem('koloni-key')).toBe('k1')
  const sent = vi.fn<typeof fetch>(async () => new Response('[]'))
  vi.stubGlobal('fetch', sent)
  await api.get('/projects')
  await api.post('/projects', { name: 'p' })
  expect(sent.mock.calls[0][1]).toMatchObject({ headers: { 'X-KOLONI-Key': 'k1' } })
  expect(sent.mock.calls[1][1]).toMatchObject({ headers: { 'X-KOLONI-Key': 'k1', 'Content-Type': 'application/json' } })
  // Where a header cannot go: an event stream, an image's source.
  expect(withKey('/api/conversations/c/events?after=3')).toBe('/api/conversations/c/events?after=3&key=k1')
  expect(withKey('/api/attachments/a/file')).toBe('/api/attachments/a/file?key=k1')
})

test('a page KOLONİ opened itself exchanges its one-time code for the key, once, and the code leaves the address', async () => {
  history.replaceState(null, '', '/#open=c0de')
  const sent = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ key: 'k2' })))
  vi.stubGlobal('fetch', sent)
  await takeKey()
  expect(sent).toHaveBeenCalledWith('/api/open', expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: 'c0de' }) }))
  expect(location.hash).toBe('')
  expect(localStorage.getItem('koloni-key')).toBe('k2')
  expect(withKey('/api/x')).toBe('/api/x?key=k2')
  // Refused (used, or late): nothing is kept, and the code still leaves the address.
  localStorage.removeItem('koloni-key')
  history.replaceState(null, '', '/#open=c0de')
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
  await takeKey()
  expect(location.hash).toBe('')
  expect(localStorage.getItem('koloni-key')).toBeNull()
})

test('a download carries the key in its header, never in an address the browser keeps, and is saved under the name its answer gives', async () => {
  localStorage.setItem('koloni-key', 'k3')
  const sent = vi.fn<typeof fetch>(async () => new Response('# core', { headers: { 'Content-Disposition': 'attachment; filename="MEMORY.md"' } }))
  vi.stubGlobal('fetch', sent)
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:core'), revokeObjectURL: vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await download('GET', '/projects/p/memory/export')
  expect(sent).toHaveBeenCalledWith('/api/projects/p/memory/export', expect.objectContaining({ method: 'GET', headers: { 'X-KOLONI-Key': 'k3' } }))
  const link = click.mock.contexts[0] as HTMLAnchorElement
  expect([link.href, link.download]).toEqual(['blob:core', 'MEMORY.md'])
  // A refusal throws, as any request's, and nothing is saved.
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'origin not allowed' }), { status: 403 })))
  await expect(download('POST', '/backup/export')).rejects.toThrow('origin not allowed')
  expect(click).toHaveBeenCalledTimes(1)
  click.mockRestore()
})

test('denetim-010 #20: a new #key= replaces the kept key only once the server takes it; a wrong one never locks the page out', async () => {
  localStorage.setItem('koloni-key', 'old')
  history.replaceState(null, '', '/#key=bad')
  const asked = vi.fn<typeof fetch>(async () => new Response('{}', { status: 401 }))
  vi.stubGlobal('fetch', asked)
  await takeKey()
  expect(asked).toHaveBeenCalledWith('/api/answer-in', expect.objectContaining({ headers: { 'X-KOLONI-Key': 'bad' }, signal: expect.any(AbortSignal) }))
  expect(localStorage.getItem('koloni-key')).toBe('old')
  expect(withKey('/api/x')).toBe('/api/x?key=old')
  expect(location.hash).toBe('')
  expect(keyRefused.now()).toBe(false)
  // Not a yes either: a proxy's 500 says nothing of the key.
  history.replaceState(null, '', '/#key=bad')
  vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })))
  await takeKey()
  expect(localStorage.getItem('koloni-key')).toBe('old')
  expect(location.hash).toBe('')
  // Not reached at all (KOLONİ stopped): the kept one stays.
  history.replaceState(null, '', '/#key=other')
  vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
  await takeKey()
  expect(localStorage.getItem('koloni-key')).toBe('old')
  expect(location.hash).toBe('')
  // KOLONİ's own new link (a new start makes a new key): taken.
  history.replaceState(null, '', '/#key=new')
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"answer_in":null}')))
  await takeKey()
  expect(localStorage.getItem('koloni-key')).toBe('new')
  expect(location.hash).toBe('')
  // The same key again asks nothing.
  history.replaceState(null, '', '/#key=new')
  const again = vi.fn<typeof fetch>()
  vi.stubGlobal('fetch', again)
  await takeKey()
  expect(again).not.toHaveBeenCalled()
  expect(location.hash).toBe('')
})

// Last in this file: once refused, the page stays so.
test('a page the server refuses for want of the key says to open KOLONİ from its window, and nothing else', async () => {
  // (Any 401, whatever it says: only the key is asked with one.)
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Open KOLONİ from the link in its window')
  expect(screen.getByText('Each start of KOLONİ makes a new link.')).toBeInTheDocument()
  expect(screen.queryByRole('button')).toBeNull()
})
