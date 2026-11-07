import { expect, test } from 'vitest'
import { FIT_MAX_ZOOM, MIN_ZOOM, centredOn, fitNarrowed, fitted, freePart, keepInView, keepWork } from './viewport'

/** A turn 1000 wide and 200 high, and its Coder at the right end of it. */
const turn = { x: 0, y: 0, width: 1000, height: 200 }
const coder = { x: 800, y: 0, width: 200, height: 200 }
const full = { width: 1200, height: 800 }
/** The same stage with the inspector open beside it. */
const narrow = { width: 700, height: 800 }

/** Where a rectangle of the turn is drawn on the stage. */
const drawn = (view: { x: number; y: number; zoom: number }, rect: typeof coder) => ({
  left: rect.x * view.zoom + view.x,
  right: (rect.x + rect.width) * view.zoom + view.x,
  top: rect.y * view.zoom + view.y,
  bottom: (rect.y + rect.height) * view.zoom + view.y,
})

test('a fit takes in the whole turn; a turn of a few nodes is drawn a little closer than life-size, and no closer', () => {
  const view = fitted(turn, full)
  expect(view.zoom).toBeLessThanOrEqual(FIT_MAX_ZOOM)
  expect(drawn(view, turn).left).toBeGreaterThanOrEqual(0)
  expect(drawn(view, turn).right).toBeLessThanOrEqual(full.width)
  // a turn wider than the stage is drawn smaller than life-size, as ever
  expect(fitted({ ...turn, width: 3000 }, full).zoom).toBeLessThan(1)
  // a small turn (a request and its lead) is not lost in the stage, and is not blown up either
  const small = { x: 0, y: 0, width: 510, height: 104 }
  const close = fitted(small, full)
  expect(close.zoom).toBe(FIT_MAX_ZOOM)
  expect(FIT_MAX_ZOOM).toBeGreaterThan(1)
  expect(FIT_MAX_ZOOM).toBeLessThanOrEqual(1.3)
  // however small the stage, no node leaves the view
  for (const stage of [full, narrow, { width: 320, height: 240 }]) {
    const at = drawn(fitted(small, stage), small)
    expect(at.left).toBeGreaterThanOrEqual(0)
    expect(at.right).toBeLessThanOrEqual(stage.width)
    expect(at.top).toBeGreaterThanOrEqual(0)
    expect(at.bottom).toBeLessThanOrEqual(stage.height)
  }
})

test('a panel opening beside the stage does not change the zoom: a selected node still in view stays where it is', () => {
  const view = { x: 20, y: 300, zoom: 0.5 }
  // the Coder is drawn from 420 to 520: inside the narrowed stage
  expect(keepInView(view, narrow, coder)).toEqual(view)
  // with nothing lying over it, too
  expect(keepInView(view, narrow, coder, [{ x: 0, y: 500, width: 300, height: 300 }])).toEqual(view)
})

test('a selected node the narrowed stage no longer shows is brought to its middle - by moving the view, at the zoom it had', () => {
  const view = fitted(turn, full)
  // fitted to the full stage the Coder ends near its right edge: the narrowed stage cuts it off
  expect(drawn(view, coder).right).toBeGreaterThan(narrow.width)
  const kept = keepInView(view, narrow, coder)
  expect(kept.zoom).toBe(view.zoom)
  const at = drawn(kept, coder)
  expect((at.left + at.right) / 2).toBeCloseTo(narrow.width / 2)
  expect((at.top + at.bottom) / 2).toBeCloseTo(narrow.height / 2)
  // one only partly out of the stage is brought in too
  const half = keepInView({ x: -900, y: 0, zoom: 1 }, narrow, coder)
  expect(drawn(half, coder).left).toBeGreaterThanOrEqual(0)
  expect(half.zoom).toBe(1)
})

test('a selected node that a window over the stage covers is moved to the middle of the largest part left free', () => {
  // an agent's window lies over the bottom left of the stage, 520 by 360
  const window = { x: 14, y: 426, width: 520, height: 360 }
  // the Coder drawn at 100..300 by 500..700: under the window
  const view = { x: -700, y: 500, zoom: 1 }
  const kept = keepInView(view, full, coder, [window])
  expect(kept.zoom).toBe(1)
  const at = drawn(kept, coder)
  // free of the window: right of it (the larger part of this stage)
  expect(at.left).toBeGreaterThanOrEqual(window.x + window.width)
  expect((at.left + at.right) / 2).toBeCloseTo((534 + 1200) / 2)
  expect((at.top + at.bottom) / 2).toBeCloseTo(400)
  // on a narrow stage the larger free part is above the window
  const above = drawn(keepInView(view, { width: 600, height: 800 }, coder, [window]), coder)
  expect(above.bottom).toBeLessThanOrEqual(window.y)
  expect((above.left + above.right) / 2).toBeCloseTo(300)
})

test('a fit on a stage a panel has narrowed is no further out than the fit at the stage’s full width', () => {
  const wide = fitted(turn, full)
  const tight = fitted(turn, narrow)
  // (what used to happen: the whole turn squeezed into what is left, too small to read)
  expect(tight.zoom).toBeLessThan(wide.zoom)
  const view = fitNarrowed(turn, narrow, full.width, null)
  expect(view.zoom).toBe(wide.zoom)
  // the turn is centred: it runs out of the stage on both sides alike
  expect(drawn(view, turn).left).toBeCloseTo(narrow.width - drawn(view, turn).right)
  // with a node selected, that node is in view
  const selected = fitNarrowed(turn, narrow, full.width, coder)
  expect(selected.zoom).toBe(wide.zoom)
  expect(drawn(selected, coder).left).toBeGreaterThanOrEqual(0)
  expect(drawn(selected, coder).right).toBeLessThanOrEqual(narrow.width)
})

test('84b2: Ready for you is never left out of the fit - where it would be, the whole turn is fitted in what is left', () => {
  // (Ready at the turn's right end: centred at the full width's zoom, it runs off the narrowed stage.)
  const ready = { x: turn.x + turn.width - 200, y: turn.y, width: 200, height: 120 }
  const cut = drawn(fitNarrowed(turn, narrow, full.width, null), ready)
  expect(cut.right).toBeGreaterThan(narrow.width)
  const view = fitNarrowed(turn, narrow, full.width, null, ready)
  expect(view).toEqual(fitted(turn, narrow))
  expect(drawn(view, ready).right).toBeLessThanOrEqual(narrow.width)
  // in view at that zoom anyway: the zoom is kept, as ever
  const inView = { ...ready, x: turn.x + turn.width / 2 - 100 }
  expect(fitNarrowed(turn, narrow, full.width, null, inView).zoom).toBe(fitted(turn, full).zoom)
})

test('a turn that fits the narrowed stage at that zoom anyway is fitted to it as ever', () => {
  const small = { x: 0, y: 0, width: 400, height: 200 }
  expect(fitNarrowed(small, narrow, full.width, null)).toEqual(fitted(small, narrow))
  // and a stage that is not narrowed is simply fitted
  expect(fitNarrowed(turn, full, full.width, null)).toEqual(fitted(turn, full))
})

test('centring keeps the zoom and puts the middle of the turn in the middle of the stage', () => {
  const view = centredOn(turn, narrow, 0.6)
  expect(view.zoom).toBe(0.6)
  expect((drawn(view, turn).left + drawn(view, turn).right) / 2).toBeCloseTo(350)
  expect((drawn(view, turn).top + drawn(view, turn).bottom) / 2).toBeCloseTo(400)
})

test('as the stage narrows, the selected node and the nodes at work stay in view: zoomed out as little as that needs, never under the least zoom', () => {
  const work = { x: 0, y: 0, width: 200, height: 200 }
  const at1 = { x: 0, y: 0, zoom: 1 }
  const seen = (view: { x: number; y: number; zoom: number }, rect: typeof coder, stage: typeof narrow) => {
    const box = drawn(view, rect)
    return box.left >= 0 && box.right <= stage.width && box.top >= 0 && box.bottom <= stage.height
  }
  // all of it fits the full stage at this zoom: the zoom stays
  const wide = keepWork(at1, full, coder, work)
  expect(wide.zoom).toBe(1)
  expect(seen(wide, coder, full) && seen(wide, work, full)).toBe(true)
  // not the narrowed one: zoomed out just enough for both
  const narrowed = keepWork(at1, narrow, coder, work)
  expect(narrowed.zoom).toBeLessThan(1)
  expect(narrowed.zoom).toBeGreaterThan(0.6)
  expect(seen(narrowed, coder, narrow) && seen(narrowed, work, narrow)).toBe(true)
  // what would need a zoom under the least: the selected node first, at the zoom it had
  const far = { x: -6000, y: 0, width: 200, height: 200 }
  const first = keepWork(at1, narrow, coder, far)
  expect(first.zoom).toBe(1)
  expect(seen(first, coder, narrow)).toBe(true)
  // the nodes at work alone, with none selected; and nothing to keep, nothing moves
  const alone = keepWork(at1, narrow, null, { x: 0, y: 0, width: 1000, height: 200 })
  expect(seen(alone, { x: 0, y: 0, width: 1000, height: 200 }, narrow)).toBe(true)
  expect(keepWork(at1, narrow, null, null)).toBe(at1)
  // a selected node alone keeps the zoom, as ever
  expect(keepWork(at1, narrow, coder, null).zoom).toBe(1)
  expect(MIN_ZOOM).toBeGreaterThan(0)
})

test('B-149: beside a tall chat the Lead and the night’s report are kept in the strip above it, not left under the inspector', () => {
  // (Live, 1219 px, the chat open: the inspector narrowed the stage to 839 px and nothing moved; the report lay under it.)
  const [stage, chat] = [{ width: 839, height: 613 }, { x: 14, y: 200, width: 480, height: 399 }]
  const [lead, report] = [{ x: 290, y: 0, width: 248, height: 222 }, { x: 898, y: 0, width: 560, height: 397 }]
  const view = keepWork({ x: 522, y: 230, zoom: 0.387 }, stage, lead, report, [chat])
  for (const rect of [lead, report]) {
    const box = drawn(view, rect)
    expect([box.left >= 0, box.right <= stage.width, box.top >= 0, box.bottom <= chat.y]).toEqual([true, true, true, true])
  }
  // Where even the least zoom cannot hold both: the report wholly in view, the selected node beside it as far as it goes.
  const tight = { width: 500, height: 600 }
  const [selected, far] = [{ x: 0, y: 0, width: 400, height: 200 }, { x: 1500, y: 0, width: 400, height: 200 }]
  const least = keepWork({ x: 0, y: 0, zoom: 1 }, tight, selected, far)
  expect(least.zoom).toBe(MIN_ZOOM)
  expect(drawn(least, far).left >= 0 && drawn(least, far).right <= tight.width).toBe(true)
  expect(drawn(least, selected).right).toBeGreaterThan(0)
})

test('a fit into a part of the stage - beside the chat - is drawn in that part, its corner counted once', () => {
  const part = { x: 494, y: 10, ...narrow }
  const small = { x: 0, y: 0, width: 400, height: 200 }
  const plain = fitted(small, narrow)
  expect(fitNarrowed(small, part, full.width, null)).toEqual({ ...plain, x: plain.x + 494, y: plain.y + 10 })
  // centred, with the selected node in view: in the part, not to the right of it
  const view = fitNarrowed(turn, part, full.width, coder)
  expect(drawn(view, coder).left).toBeGreaterThanOrEqual(494)
  expect(drawn(view, coder).right).toBeLessThanOrEqual(494 + narrow.width)
  expect(drawn(fitNarrowed(turn, part, full.width, null), turn).left - 494).toBeCloseTo(494 + narrow.width - drawn(fitNarrowed(turn, part, full.width, null), turn).right)
})

test('two windows in opposite corners: the free part is a large one between them, not a strip beside both (slice 38e)', () => {
  // the view window top left, the chat moved to the bottom right
  const view = { x: 48, y: 0, width: 692, height: 380 }
  const chat = { x: 900, y: 470, width: 480, height: 378 }
  const free = freePart({ width: 1384, height: 848 }, [view, chat])
  // clear of both
  for (const cover of [view, chat])
    expect(free.x + free.width <= cover.x || cover.x + cover.width <= free.x || free.y + free.height <= cover.y || cover.y + cover.height <= free.y).toBe(true)
  // and as large as a third of the stage, not a strip
  expect(free.width * free.height).toBeGreaterThan((1384 * 848) / 3)
  expect(Math.min(free.width, free.height)).toBeGreaterThan(300)
  // nothing over the stage: all of it
  expect(freePart({ width: 1384, height: 848 }, [])).toEqual({ x: 0, y: 0, width: 1384, height: 848 })
})
