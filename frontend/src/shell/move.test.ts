import { afterEach, describe, expect, test } from 'vitest'
import { placeWindow, storedSpot, toFront, within } from './move'

afterEach(() => {
  localStorage.clear()
  document.body.innerHTML = ''
})

test('a kept place is read back; anything else is no place, and the window is in its corner', () => {
  localStorage.setItem('k', '{"x":120,"y":40}')
  expect(storedSpot('k')).toEqual({ x: 120, y: 40 })
  for (const bad of ['nonsense', '{"x":"a","y":1}', '{"x":-5,"y":1}', '[1,2]', 'null', '{"x":1}'])
    expect(storedSpot((localStorage.setItem('k', bad), 'k'))).toBeNull()
  expect(storedSpot('none')).toBeNull()
})

test('a window is kept inside the stage: never past an edge; as far left as its corner, and clear of the zoom buttons at the bottom right', () => {
  const box = { width: 400, height: 300 }
  const stage = { width: 1000, height: 800 }
  expect(within({ x: 900, y: 700 }, box, stage)).toEqual({ x: 600, y: 500 })
  expect(within({ x: -20, y: -3 }, box, stage)).toEqual({ x: 14, y: 0 })
  // Its foot beside the buttons (the stage's bottom 232px): no nearer the right than 48.
  expect(within({ x: 900, y: 0 }, box, stage)).toEqual({ x: 552, y: 0 })
  expect(within({ x: 900, y: 231 }, box, stage)).toEqual({ x: 552, y: 231 })
  expect(within({ x: 900, y: 232 }, box, stage)).toEqual({ x: 600, y: 232 })
  expect(within({ x: -20, y: 100 }, box, stage)).toEqual({ x: 14, y: 100 })
})

test('the window clicked last is the one in front; the rest are side by side behind it', () => {
  document.body.innerHTML = '<div class="stage"><section class="chat"></section><section class="view-panel"></section><section class="changes"></section></div>'
  const [chat, view, changes] = ['.chat', '.view-panel', '.changes'].map(s => document.querySelector(s)!)
  toFront(view)
  expect(view).toHaveAttribute('data-front')
  toFront(chat)
  expect(chat).toHaveAttribute('data-front')
  expect(view).not.toHaveAttribute('data-front')
  expect(changes).not.toHaveAttribute('data-front')
})

describe('K-38b-sinirlar: a window opening in the top right', () => {
  const stage = { width: 600, height: 670 }
  // As its CSS puts it: top right, 320 wide, 360 tall.
  const want = { left: 266, top: 14, width: 320, height: 360 }
  const chat = (left: number, top: number, width: number, height: number) => ({ left, top, width, height })

  test('stays where its CSS puts it, on a stage wide enough for both', () => {
    expect(placeWindow(want, stage, chat(14, 356, 230, 300), [])).toBe(want)
    expect(placeWindow(want, stage, null, [])).toBe(want)
  })

  test('narrow: made shorter, to end above the chat at the bottom left', () => {
    expect(placeWindow(want, stage, chat(14, 356, 480, 300), [])).toEqual({ left: 266, top: 14, width: 320, height: 328 })
  })

  test('a chat as tall as the stage: beside it, as narrow as there is room for - or over it, where none is', () => {
    expect(placeWindow(want, stage, chat(14, 16, 300, 640), [])).toEqual({ left: 328, top: 14, width: 258, height: 360 })
    expect(placeWindow(want, stage, chat(14, 16, 480, 640), [])).toBe(want)
  })

  test('a chat moved to the top right: left of it, or below it, wherever is more room - never past the stage', () => {
    expect(placeWindow(want, stage, chat(330, 14, 256, 300), [])).toEqual({ left: 14, top: 14, width: 302, height: 360 })
    expect(placeWindow(want, stage, chat(100, 14, 486, 200), [])).toEqual({ left: 266, top: 228, width: 320, height: 360 })
    expect(placeWindow({ ...want, height: 600 }, stage, chat(100, 14, 486, 200), [])).toEqual({ left: 266, top: 228, width: 320, height: 428 })
  })

  test('cascades below the header of a window it would lie over, while it stays tall enough', () => {
    expect(placeWindow(want, stage, null, [{ left: 200, top: 56, width: 380, height: 500 }])).toEqual({ left: 266, top: 106, width: 320, height: 268 })
    // (too short below that header: it stays, in front)
    expect(placeWindow(want, stage, null, [{ left: 200, top: 200, width: 380, height: 300 }])).toBe(want)
    // (beside it, or under its header already: as it was)
    expect(placeWindow(want, stage, null, [{ left: 14, top: 14, width: 200, height: 300 }])).toBe(want)
  })
})
