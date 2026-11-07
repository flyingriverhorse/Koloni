// Slice 66 in the browser: the rail says each page's name under its icon, readable in both
// themes and on a short window; the model server down is one calm line with a way out; the
// canvas's buttons and the turn stand clear of the open chat.
import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, OWN, rail, settled, shot } from './helpers'

type Box = { x: number; y: number; width: number; height: number }
// (as 38e's)
const inside = (inner: Box, outer: Box) =>
  inner.x >= outer.x - 1 && inner.y >= outer.y - 1 && inner.x + inner.width <= outer.x + outer.width + 1 && inner.y + inner.height <= outer.y + outer.height + 1
const apart = (a: Box, b: Box) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y

const NAMES = ['Canvas', 'Chats', 'Ready', 'Board', 'To-do', 'Agents', 'Models', 'Tools', 'Memory', 'Knowledge', 'Triggers', 'Usage', 'Settings', 'Theme']

for (const theme of ['light', 'dark'] as const)
  test(`the rail's buttons say their names under their icons, at 4.5 or more, in the ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 700 })
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    // A question waiting for the user: the Ready button counts it, and the top bar's pill (tek-ev §1).
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByLabel('Message').fill('review the greeting carefully')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.locator('.ready-pill')).toHaveText(/^\d+ waits?$/)
    await expect(nav.locator('.rail-badge')).toBeVisible()
    // Two digits still fit on the button, inside the rail.
    const badge = await nav.locator('.rail-badge').evaluate(el => {
      el.textContent = '12'
      const [b, r] = [el.getBoundingClientRect(), el.closest('.rail')!.getBoundingClientRect()]
      return b.left >= r.left && b.right <= r.right && b.top >= r.top
    })
    expect(badge).toBe(true)
    try {
      await settled(page)
      if (process.env.KOLONI_SHOTS) await shot(page, `66-main-${theme}`)
      // (one pressed: its colours are the accent's)
      await rail(page, 'Board').click()
      for (const name of NAMES) {
        const label = nav.locator('.rail-label', { hasText: name })
        await expect(label).toBeVisible()
        // Whole on the 700px window, not cut by its edge.
        const at = (await label.boundingBox())!
        expect(at.y + at.height).toBeLessThanOrEqual(700)
      }
      // What a button says is a word of its name (WCAG 2.5.3): a speech user can say it.
      const said = await nav.locator('button:has(.rail-label)').evaluateAll(all => all.map(b => [b.querySelector('.rail-label')!.textContent!, b.getAttribute('aria-label')!]))
      expect(said).toHaveLength(NAMES.length)
      for (const [label, name] of said) expect(name.toLowerCase()).toContain(label.toLowerCase())
      const pieces = await nav.evaluate(contrasts)
      expect(pieces.filter(piece => NAMES.includes(piece.text)).length).toBe(NAMES.length)
      expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
      if (process.env.KOLONI_SHOTS) await shot(page, `66-rail-${theme}`)
    } finally {
      // (answered: nothing is left waiting for the specs after this one)
      await rail(page, 'Canvas').click()
      await chat.getByRole('button', { name: 'strict', exact: true }).click()
      await expect(page.getByText('DONE', { exact: true })).toBeVisible()
    }
  })

test('on a window 480px tall the rail scrolls up and down, never sideways, and a focused button shows its ring inside it', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 480 })
  await openFreshConversation(page)
  const nav = page.getByRole('navigation', { name: 'Main' })
  const sizes = await nav.evaluate(el => [el.scrollWidth, el.clientWidth, el.scrollHeight, el.clientHeight])
  expect(sizes[0]).toBeLessThanOrEqual(sizes[1])
  expect(sizes[2]).toBeGreaterThan(sizes[3])
  // The theme button, last, is reached by scrolling - from the keyboard too.
  const theme = nav.getByRole('button', { name: /^Theme/ })
  await theme.focus()
  await expect(theme).toBeInViewport()
  const [ring, inside] = await theme.evaluate(el => {
    const [b, r] = [el.getBoundingClientRect(), el.closest('.rail')!.getBoundingClientRect()]
    return [getComputedStyle(el).outlineOffset, b.left >= r.left && b.right <= r.right - 1]
  })
  expect(ring).toBe('-2px')
  expect(inside).toBe(true)
  if (process.env.KOLONI_SHOTS) await shot(page, '66-rail-short')
})

test("the model server down: one short line, its reason behind Details, and Pick another model opens Models", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'light'))
  const [local]: { id: string; base_url: string }[] = await (await page.request.get('/api/providers')).json()
  const point = (base_url: string) => page.request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { base_url } })
  // Nothing listens on port 9: the default provider cannot be reached.
  expect((await point('http://127.0.0.1:9/v1')).ok()).toBe(true)
  try {
    await openFreshConversation(page)
    const banner = page.locator('.banner')
    await expect(banner.getByRole('status')).toHaveText("Local isn't answering at 127.0.0.1:9.", { timeout: 15_000 })
    const why = banner.locator('.banner-why')
    await expect(why).toBeHidden()
    await banner.getByRole('button', { name: 'Details' }).click()
    await expect(why).toBeVisible()
    await expect(why).toContainText('unreachable')
    // (and readable in both themes)
    for (const theme of ['light', 'dark']) {
      await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(theme === 'dark')
      expect((await banner.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      if (process.env.KOLONI_SHOTS) await shot(page, `66-banner-${theme}`)
      await page.getByRole('button', { name: /^Theme: switch to (dark|light)$/ }).click()
    }
    await banner.getByRole('button', { name: 'Pick another model' }).click()
    await expect(rail(page, 'Models')).toHaveAttribute('aria-pressed', 'true')
  } finally {
    // (put back: every spec after this one talks to the fake model)
    expect((await point(local.base_url)).ok()).toBe(true)
  }
})

for (const size of [{ width: 1440, height: 900 }, { width: 1366, height: 768 }])
  test(`at ${size.width}x${size.height} the open chat covers neither the canvas's buttons nor the turn's nodes`, async ({ page }) => {
    await page.setViewportSize(size)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByLabel('Message').fill('have both files reviewed')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(3)
    await expect(chat.getByText('Both reviewers are done.')).toBeVisible({ timeout: 15_000 })
    await settled(page)
    const [over, stage, buttons] = [(await chat.boundingBox())!, (await page.locator('.canvas-flow').boundingBox())!, (await page.locator('.react-flow__controls').boundingBox())!]
    expect(apart(buttons, over)).toBe(true)
    // (and pressable: nothing else lies over them)
    const zoomIn = (await page.getByRole('button', { name: 'Zoom In' }).boundingBox())!
    expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('.react-flow__controls'), [zoomIn.x + zoomIn.width / 2, zoomIn.y + zoomIn.height / 2])).toBe(true)
    for (const node of await page.locator('.react-flow__node').all()) {
      const at = (await node.boundingBox())!
      expect(inside(at, stage) && apart(at, over), `${await node.innerText()} at ${JSON.stringify(at)}`).toBe(true)
    }
    if (process.env.KOLONI_SHOTS) await shot(page, `66-canvas-${size.width}x${size.height}`)
    // Fitted, no node goes under the buttons (K-66-kalan). (Its agents are small nodes: nothing to expand - the user's, 5 Nov.)
    await page.getByRole('button', { name: 'Fit View' }).click()
    await settled(page)
    for (const node of await page.locator('.react-flow__node').all()) {
      const at = (await node.boundingBox())!
      expect(inside(at, stage) && apart(at, over) && apart(at, buttons), `${await node.innerText()} at ${JSON.stringify(at)}`).toBe(true)
    }
    if (process.env.KOLONI_SHOTS) await shot(page, `66-canvas-expanded-${size.width}x${size.height}`)
  })

// (1024 wide: a stage under ~1044px, where the Workspace window came over the buttons before K-66-kalan.)
test("at 1024x720 the Workspace window and a toast leave the canvas's buttons free to press", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 720 })
  await openFreshConversation(page)
  const buttons = page.locator('.react-flow__controls')
  const pressable = async () => {
    const zoomIn = (await page.getByRole('button', { name: 'Zoom In' }).boundingBox())!
    return page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('.react-flow__controls'), [zoomIn.x + zoomIn.width / 2, zoomIn.y + zoomIn.height / 2])
  }
  await page.getByRole('button', { name: /^Workspace/ }).click()
  const files = page.getByRole('region', { name: 'Workspace' })
  await expect(files).toBeVisible()
  // (Polled: the window takes its width from its stage as that is measured - a frame or more after it shows.)
  const free = async (over: typeof files) => apart((await over.boundingBox())!, (await buttons.boundingBox())!) && (await pressable())
  await expect.poll(() => free(files)).toBe(true)
  // Another conversation begins to wait (its turn asks to run a command): its toast stands above the buttons.
  const project = (await (await page.request.get('/api/projects')).json())[0].id
  const other: string = (await (await page.request.post('/api/conversations', { data: { project_id: project }, headers: OWN })).json()).id
  const title = `toast ${Date.now()} run it slowly`
  expect((await page.request.post(`/api/conversations/${other}/messages`, { data: { content: title }, headers: OWN })).ok()).toBe(true)
  try {
    const toast = page.locator('.toast', { hasText: title })
    await expect(toast).toBeVisible({ timeout: 15_000 })
    await expect.poll(() => free(toast)).toBe(true)
    if (process.env.KOLONI_SHOTS) await shot(page, '66-buttons-free-1024')
  } finally {
    await expect.poll(async () => (await (await page.request.get(`/api/conversations/${other}`)).json()).commands.length, { timeout: 15_000 }).toBeGreaterThan(0)
    for (const command of (await (await page.request.get(`/api/conversations/${other}`)).json()).commands)
      await page.request.post(`/api/commands/${command.id}/reject`, { headers: OWN })
  }
})

// (600px tall: there the window, 360px, came down over the buttons before slice 66's cap.)
for (const height of [720, 600])
  test(`at 1280x${height} an agent's window, top right, ends above the canvas's buttons, bottom right`, async ({ page }) => {
  await page.setViewportSize({ width: 1280, height })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible({ timeout: 20_000 })
  await page.locator('.react-flow__node-agent', { hasText: 'Reviewer' }).click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  await expect(own).toBeVisible()
  const [window, buttons] = [(await own.boundingBox())!, (await page.locator('.react-flow__controls').boundingBox())!]
  expect(apart(window, buttons), `${JSON.stringify(window)} / ${JSON.stringify(buttons)}`).toBe(true)
  if (process.env.KOLONI_SHOTS) await shot(page, `66-agent-window-${height}`)
  await own.getByRole('button', { name: 'Close agent window' }).click()
})
