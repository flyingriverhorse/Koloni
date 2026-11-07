// Slice 58 in the browser: a 3D part an agent writes, or one it shows, opens Files on a 3D view -
// three.js asked for only then. Its bounding box in words; Fit, Reset view, Wireframe and the keys
// change what is drawn; written again on disk it is drawn anew, seen from where it was. Every text
// at 4.5 in both themes.
import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation } from './helpers'
import { boxStl, triangleGlb } from './models58.mjs'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const STL = path.join(PROJECT_DIR, 'part58.stl')
const GLB = path.join(PROJECT_DIR, 'part58.glb')
// (by its class: the window's name and buttons are another slice's to change)
const windowOf = (page: Page) => page.locator('.view-panel')
const figureOf = (page: Page, name: string) => windowOf(page).getByRole('figure', { name })
/** Whether the 3D view's own code was asked for. */
const threeAsked = (page: Page) => page.evaluate(() => performance.getEntriesByType('resource').some(entry => /\/ModelView-[\w-]+\.js$/.test(entry.name)))
/** What the view draws, as a picture: the camera moved, it is another. */
const drawn = (figure: Locator) => figure.locator('canvas').screenshot()

/** A fresh conversation, once its views were first listed: what an agent shows after is new, and opens Files. */
async function freshListed(page: Page) {
  const listed = new Set<string>()
  page.on('response', r => {
    const read = r.request().method() === 'GET' && r.url().match(/\/api\/conversations\/([0-9a-f]{32})\/views$/)
    if (read) listed.add(read[1])
  })
  const id = await openFreshConversation(page)
  await expect.poll(() => listed.has(id), { timeout: 10_000 }).toBe(true)
  return id
}
async function rejectWaiting(page: Page, id: string) {
  if (!id) return
  const conv = await (await page.request.get(`/api/conversations/${id}`)).json()
  for (const change of conv.file_changes ?? [])
    if (change.status === 'proposed') await page.request.post(`/api/file-changes/${change.id}/reject`, { headers: OWN })
}

test.beforeAll(() => writeFileSync(GLB, triangleGlb()))
test.afterAll(() => [STL, GLB].forEach(file => rmSync(file, { force: true })))

test('a part an agent writes opens Files on its 3D view - three.js asked for only then; its box in words; the keys, Fit, Reset view and Wireframe; written again it is drawn anew, seen from where it was', async ({ page }) => {
  test.setTimeout(90_000)
  let id = ''
  try {
    id = await freshListed(page)
    expect(await threeAsked(page)).toBe(false)
    await page.getByLabel('Message').fill('make the part')
    await page.getByRole('button', { name: 'Send' }).click()
    const figure = figureOf(page, 'part58.stl')
    // (while it waits for you, drawn as it will be: the model, not its diff)
    await expect(figure).toBeVisible({ timeout: 20_000 })
    await expect(figure.locator('figcaption')).toHaveText(/ · 10 × 20 × 30 · 12 triangles$/, { timeout: 10_000 })
    expect(await threeAsked(page)).toBe(true)
    await expect(windowOf(page).getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')

    const first = await drawn(figure)
    await figure.focus()
    await page.keyboard.press('ArrowLeft')
    const turned = await drawn(figure)
    expect(turned.equals(first)).toBe(false)
    await figure.getByRole('button', { name: 'Reset view' }).click()
    expect((await drawn(figure)).equals(first)).toBe(true)
    // zoomed out, Fit brings the whole part back as near as it was
    await figure.focus()
    for (let n = 0; n < 3; n++) await page.keyboard.press('-')
    const far = await drawn(figure)
    expect(far.equals(first)).toBe(false)
    await figure.getByRole('button', { name: 'Fit' }).click()
    expect((await drawn(figure)).equals(far)).toBe(false)
    const wire = figure.getByRole('button', { name: 'Wireframe' })
    await expect(wire).toHaveAttribute('aria-pressed', 'false')
    const solid = await drawn(figure)
    await wire.click()
    await expect(wire).toHaveAttribute('aria-pressed', 'true')
    expect((await drawn(figure)).equals(solid)).toBe(false)
    await wire.click()

    await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText('The part is written.')).toBeVisible({ timeout: 20_000 })
    // turned, then written again by something else: drawn anew, still turned (Reset view moves it)
    await figure.focus()
    for (let n = 0; n < 3; n++) await page.keyboard.press('ArrowRight')
    writeFileSync(STL, boxStl(10, 20, 60))
    await expect(figure.locator('figcaption')).toHaveText(/ · 10 × 20 × 60 · 12 triangles$/, { timeout: 10_000 })
    const kept = await drawn(figure)
    await figure.getByRole('button', { name: 'Reset view' }).click()
    expect((await drawn(figure)).equals(kept)).toBe(false)
  } finally {
    await rejectWaiting(page, id)
  }
})

test('a GLB an agent shows opens Files on it, read from the project as it is', async ({ page }) => {
  test.setTimeout(60_000)
  await freshListed(page)
  await page.getByLabel('Message').fill('show the glb')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('There is the part.')).toBeVisible({ timeout: 20_000 })
  const figure = figureOf(page, 'part58.glb')
  await expect(figure.locator('figcaption')).toHaveText(/ · 4 × 5 × 0 m · 1 triangle$/, { timeout: 10_000 })
  await expect(windowOf(page)).toContainText('the part, as glTF')
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme the 3D view's buttons and words stand out from what they are on (contrast 4.5 or more), on the theme's own ground`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await freshListed(page)
    await page.getByLabel('Message').fill('show the glb')
    await page.getByRole('button', { name: 'Send' }).click()
    const figure = figureOf(page, 'part58.glb')
    await expect(figure.locator('figcaption')).toHaveText(/triangle$/, { timeout: 20_000 })
    await figure.getByRole('button', { name: 'Wireframe' }).click()
    const pieces = await figure.evaluate(contrasts)
    expect(pieces.map(piece => piece.text)).toEqual(expect.arrayContaining(['Fit', 'Reset view', 'Wireframe']))
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    // (the ground the part is drawn on is the theme's)
    const [ground, bg] = await figure.locator('.model-canvas').evaluate(el => {
      const probe = document.createElement('div')
      probe.style.background = 'var(--bg)'
      document.body.append(probe)
      const said = getComputedStyle(probe).backgroundColor
      probe.remove()
      return [getComputedStyle(el).backgroundColor, said]
    })
    expect(ground).toBe(bg)
  })
