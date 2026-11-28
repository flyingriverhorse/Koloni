import { renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from './client'
import { CLIENT, lookingAt, useLooking } from './looking'
import { openEvents } from './sse'

/** The tab hidden or seen, as the browser says it: put back after each test (files share a worker). */
function tab(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  document.dispatchEvent(new Event('visibilitychange'))
}

afterEach(() => {
  delete (document as { hidden?: boolean }).hidden
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('the chat on screen says it is looked at, then not when its tab is hidden, its window left or it is put away', () => {
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined)
  const said = () => post.mock.calls.map(([path, body]) => [path, (body as { looking: boolean }).looking])
  const { rerender, unmount } = renderHook(({ id }) => useLooking(id), { initialProps: { id: 'c1' as string | null } })
  expect(post).toHaveBeenLastCalledWith('/conversations/c1/looking', { client: CLIENT, looking: true })
  expect(lookingAt('c1')).toBe(true)
  tab(true)
  tab(false)
  rerender({ id: null }) // (another page of KOLONİ's over the chat)
  expect(lookingAt('c1')).toBe(false)
  rerender({ id: 'c2' })
  unmount()
  expect(said()).toEqual([
    ['/conversations/c1/looking', true],
    ['/conversations/c1/looking', false],
    ['/conversations/c1/looking', true],
    ['/conversations/c1/looking', false],
    ['/conversations/c2/looking', true],
    ['/conversations/c2/looking', false],
  ])
})

test('a stream opens with this page’s id and whether it looks, and says it again once it is open', () => {
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined)
  const opened: { url: string; onopen: (() => void) | null }[] = []
  vi.stubGlobal(
    'EventSource',
    class {
      url: string
      onopen: (() => void) | null = null
      constructor(url: string) {
        this.url = url
        opened.push(this)
      }
      addEventListener() {}
      close() {}
    },
  )
  const { unmount } = renderHook(() => useLooking('c3'))
  openEvents(
    'c3',
    0,
    () => {},
    () => {},
    () => {},
  )
  openEvents(
    'c4',
    0,
    () => {},
    () => {},
    () => {},
  )
  expect(opened[0].url).toContain(`client=${CLIENT}&looking=true`)
  expect(opened[1].url).toContain('looking=false') // (not the chat on screen)
  post.mockClear()
  opened[0].onopen?.()
  opened[1].onopen?.()
  expect(post.mock.calls).toEqual([['/conversations/c3/looking', { client: CLIENT, looking: true }]])
  unmount()
})
