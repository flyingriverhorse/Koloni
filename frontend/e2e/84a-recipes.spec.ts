import { existsSync, readFileSync, rmSync, rmdirSync } from 'node:fs'
import path from 'node:path'
import { expect, type Locator, type Page, test } from './fixtures'
import { LINK, OWN, contrasts, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// Slice 84a: the Agents page's Recipes tab - a recipe drawn on its own board, checked by the server as it is saved and kept over a
// reload; a ready one read-only and copied; "Or write it" drawn by the Lead's model (the scripted one); a recipe kept in the folder's
// .koloni/recipes; a team's default recipe. What a spec makes it takes away: the other specs see the ready recipes and teams alone.
const NAME = 'Small 84a'
const DRAWN = 'Spec then code'
const TEAM = 'Game 84a'
const RECIPES = path.join(PROJECT_DIR, '.koloni', 'recipes')
type Named = { id: string; name: string }

test.afterEach(async ({ request }) => {
  const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: Named[] }
  for (const recipe of recipes)
    if (recipe.name.startsWith(NAME) || recipe.name === DRAWN) expect((await request.delete(`/api/recipes/${recipe.id}`, { headers: OWN })).ok()).toBe(true)
  for (const team of (await (await request.get('/api/teams')).json()) as Named[])
    if (team.name === TEAM) expect((await request.delete(`/api/teams/${team.id}`, { headers: OWN })).ok()).toBe(true)
  rmSync(RECIPES, { recursive: true, force: true })
  try {
    rmdirSync(path.dirname(RECIPES)) // (only an empty .koloni/: another spec's settings stay)
  } catch {
    // not there, or not empty
  }
})

const lowContrast = async (page: Page) => (await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)
const recipesTab = async (page: Page) => {
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await page.getByRole('tab', { name: 'Recipes' }).click()
}
const part = (page: Page) => page.getByRole('complementary', { name: /^Recipe part/ })
/** From now on, how many times an arrow is taken off the board: none, as the board is drawn again (B-85). */
async function arrowsTakenAway(page: Page) {
  await page.evaluate(() => {
    const seen = window as unknown as { arrowsGone: number }
    seen.arrowsGone = 0
    new MutationObserver(changes => {
      for (const change of changes)
        for (const one of change.removedNodes) if (one instanceof Element && (one.matches('.react-flow__edge') || one.querySelector('.react-flow__edge'))) seen.arrowsGone += 1
    }).observe(document.querySelector('.recipe-flow') as Element, { subtree: true, childList: true })
  })
  return () => page.evaluate(() => (window as unknown as { arrowsGone: number }).arrowsGone)
}
/** A press on `from` let go on `to`, in small moves (React Flow follows the pointer). */
async function drag(page: Page, from: Locator, to: Locator) {
  const [a, b] = [await from.boundingBox(), await to.boundingBox()]
  if (!a || !b) throw new Error('not on the board')
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 10 })
  await page.mouse.up()
}

for (const theme of ['light', 'dark'] as const) {
  test(`a recipe drawn is checked, saved and kept over a reload; a ready one is read-only and copied (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    await recipesTab(page)
    // The ready ones first; Feature on the board, read-only: four reviews at once, at most two rounds back.
    await expect(page.getByRole('button', { name: /^Feature/ })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { name: /^Bugfix/ })).toContainText('ready')
    await expect(page.getByRole('button', { name: /^Security review/ })).toBeVisible()
    await expect(page.getByText('back, at most 2 rounds')).toBeVisible()
    await expect(page.getByRole('button', { name: '+ Step' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Save recipe' })).toHaveCount(0)
    // A part chosen: who does it and what it gets, shown and not changed.
    await page.getByRole('button', { name: /^Build it/ }).click()
    await expect(part(page)).toContainText('the work of Write the spec, and the findings of All at once, wait for all when looped back')
    await expect(part(page).getByLabel('Who')).toBeDisabled()
    await shot(page, `84a-recipes-ready-${theme}`)
    expect(await lowContrast(page)).toEqual([])
    await page.getByRole('button', { name: 'Copy it' }).click()
    await expect(page.getByLabel('Recipe’s name')).toHaveValue('Feature copy')
    await expect(page.getByRole('button', { name: '+ Step' })).toBeEnabled()

    // A new one: a step no arrow reaches is said at the step, by the server.
    await page.getByRole('button', { name: '+ Draw a new recipe' }).click()
    await page.getByRole('button', { name: '+ Step' }).click()
    await page.getByLabel('Recipe’s name').fill(`${NAME} ${theme}`)
    await page.getByRole('button', { name: 'Save recipe' }).click()
    // (R57: the first part it is about chosen, its words in its panel; the others on their ⚠ - none under a node, over its arrows)
    await expect(part(page).getByRole('alert')).toContainText('Your message leads nowhere')
    await expect(page.getByRole('img', { name: /New step is not reached from Your message/ })).toBeVisible()
    // Joined from the start, given to the Coder, ended with "Ask me, then in", then saved.
    await page.getByRole('button', { name: /^Your message/ }).click()
    await part(page).getByLabel('Add an arrow to').selectOption({ label: 'New step' })
    await page.getByRole('button', { name: /^New step/ }).click()
    await part(page).getByLabel('Name').fill('Build it')
    await part(page).getByLabel('Who').selectOption('role:Coder')
    await page.getByRole('button', { name: '+ Ask me' }).click()
    // Every arrow drawn as it is made, and still drawn once saved (B-85: they were gone till the recipe was opened again).
    const arrows = page.locator('.recipe-flow .react-flow__edge')
    await expect(arrows).toHaveCount(2)
    const gone = await arrowsTakenAway(page)
    await page.getByRole('button', { name: 'Save recipe' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
    await expect(page.locator('.recipe-said')).toHaveCount(0)
    await expect(arrows).toHaveCount(2)
    expect(await gone()).toBe(0)
    await shot(page, `84a-recipes-${theme}`)
    expect(await lowContrast(page)).toEqual([])
    // Dragged where the user wants it (K-tarif-surukle), and saved with it.
    const box = async (id: string) => (await page.locator(`.react-flow__node[data-id="${id}"]`).boundingBox()) as { x: number; y: number }
    // A save refused first: its alert above the board, which the next Save takes away.
    const name = page.getByLabel('Recipe’s name')
    await name.fill('')
    await page.getByRole('button', { name: 'Save recipe' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await name.fill(`${NAME} ${theme}`)
    const from = await box('s1')
    await page.mouse.move(from.x + 20, from.y + 20)
    await page.mouse.down()
    await page.mouse.move(from.x + 180, from.y + 40, { steps: 8 })
    await page.mouse.up()
    // (React Flow starts the drag a step in: not all of the 160 px.)
    await expect.poll(async () => (await box('s1')).x - from.x).toBeGreaterThan(100)
    // How far s1 is right of the start on the drawing, both read at once: no move of the view can come between two screen reads.
    const apart = () =>
      page.evaluate(() => {
        const x = (id: string) => new DOMMatrixReadOnly(getComputedStyle(document.querySelector(`.recipe-flow .react-flow__node[data-id="${id}"]`) as Element).transform).m41
        return x('s1') - x('start')
      })
    // Where s1 is on the board (the board itself moves up as the alert goes: the page's own flow).
    const onBoard = async () => {
      const [at, board] = [await box('s1'), (await page.locator('.recipe-flow').boundingBox()) as { x: number; y: number }]
      return { x: at.x - board.x, y: at.y - board.y }
    }
    const dragged = await onBoard()
    await page.getByRole('button', { name: 'Save recipe' }).click()
    const placed = async () => {
      const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: (Named & { graph: { steps: { pos?: unknown }[] } })[] }
      return recipes.find(one => one.name === `${NAME} ${theme}`)?.graph.steps[0].pos ?? null
    }
    await expect.poll(placed).not.toBeNull()
    const moved = await apart()
    // The drawing stays where it is on the board as it is saved (the status line emptied and said again, and the refused save's
    // alert taken away, moved it 80 px aside).
    await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))))
    expect(await onBoard()).toEqual(dragged)

    // Read again from the server: all of it kept.
    await page.goto('about:blank')
    await page.goto(LINK)
    await page.getByLabel('Message').waitFor()
    await recipesTab(page)
    await page.getByRole('button', { name: new RegExp(`^${NAME} ${theme}`) }).click()
    await expect(page.getByRole('button', { name: /^Build it/ })).toContainText('Coder')
    expect(await apart()).toBe(moved)
    const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: (Named & { graph: { arrows: unknown[] } })[] }
    expect(recipes.find(one => one.name === `${NAME} ${theme}`)?.graph.arrows).toEqual([
      { from: 'start', to: 's1' },
      { from: 's1', to: 'end1' },
    ])
  })
}

test('an arrow is dragged from a part’s bottom to anywhere on another, a loop from its right side, never the other way; all of it stays in view', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  await recipesTab(page)
  await page.getByRole('button', { name: '+ Draw a new recipe' }).click()
  // s1 on its own, s2 after it.
  await page.getByRole('button', { name: '+ Step' }).click()
  await page.getByRole('button', { name: '+ Step' }).click()
  const node = (id: string) => page.locator(`.recipe-flow .react-flow__node[data-id="${id}"]`)
  const arrows = page.locator('.recipe-flow .react-flow__edge')
  await expect(arrows).toHaveCount(1)
  // Let go on the part, not on its handle: the arrow is drawn all the same.
  await drag(page, node('start').locator('[data-handleid="out"]'), node('s1'))
  await expect(arrows).toHaveCount(2)
  await node('s1').getByRole('button').click()
  await expect(part(page)).toContainText(/Gets\s*your message/)
  // From the right side of the second back to the first: a loop back - not an arrow from the first to it.
  await drag(page, node('s2').locator('[data-handleid="loop-out"]'), node('s1'))
  await expect(page.getByText('back, at most 2 rounds')).toBeVisible()
  await expect(arrows).toHaveCount(3)
  // Steps hung one after another till the drawing is taller than the board: every part still in view.
  for (let n = 0; n < 6; n += 1) await page.getByRole('button', { name: '+ Step' }).click()
  await expect(node('s8')).toBeVisible()
  // The board fits itself again a moment after a step is added: measure once it has.
  await expect(async () => {
    const board = (await page.locator('.recipe-flow').boundingBox()) as { x: number; y: number; width: number; height: number }
    for (const box of await page.locator('.recipe-flow .react-flow__node').evaluateAll(all => all.map(one => one.getBoundingClientRect().toJSON())))
      expect(box.top >= board.y && box.bottom <= board.y + board.height && box.left >= board.x && box.right <= board.x + board.width, JSON.stringify(box)).toBe(true)
  }).toPass({ timeout: 5000 })

  // A step taken out of its group gets arrows of its own, drawn.
  await page.getByRole('button', { name: '+ Draw a new recipe' }).click()
  await page.getByRole('button', { name: '+ All at once' }).click()
  await node('s1').getByRole('button').click()
  await part(page).getByLabel('At the same time as').selectOption('')
  await node('start').getByRole('button').click()
  await part(page).getByLabel('Add an arrow to').selectOption({ label: 'First at once' })
  // (and the group's fork to its one step left and its join from it, B-374)
  await expect(arrows).toHaveCount(3)
})

// B-108: ten steps your message did not lead to stood in one row, six of the eleven parts off the board, and Tidy up did not fit them.
test('steps your message does not lead to yet are laid out one under another; tidied up, all of them are on the board', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  await recipesTab(page)
  await page.getByRole('button', { name: '+ Draw a new recipe' }).click()
  // The first on its own, each next one after the one before.
  for (let n = 0; n < 10; n += 1) await page.getByRole('button', { name: '+ Step' }).click()
  await page.getByRole('button', { name: 'Tidy up' }).click()
  await expect(page.locator('.recipe-flow .react-flow__node[data-id="s10"]')).toBeVisible()
  const board = (await page.locator('.recipe-flow').boundingBox()) as { x: number; y: number; width: number; height: number }
  await expect
    .poll(async () =>
      (await page.locator('.recipe-flow .react-flow__node').evaluateAll(all => all.map(one => one.getBoundingClientRect().toJSON()))).filter(
        box => !(box.top >= board.y && box.bottom <= board.y + board.height && box.left >= board.x && box.right <= board.x + board.width),
      ),
    )
    .toEqual([])
})

test('a part the server refused shows ⚠ on it, and a long name stops short of the ⚠', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  await recipesTab(page)
  await page.getByRole('button', { name: '+ Draw a new recipe' }).click()
  await page.getByRole('button', { name: '+ Step' }).click()
  await part(page).getByLabel('Name').fill('A step with a name far longer than its node is wide')
  await page.getByRole('button', { name: 'Save recipe' }).click()
  const node = page.locator('.recipe-flow .react-flow__node[data-id="s1"]')
  const sign = node.getByRole('img')
  await expect(sign).toHaveAccessibleName(/is not reached from Your message/)
  const [name, warn] = [await node.locator('.recipe-node-name').boundingBox(), await sign.boundingBox()]
  expect(name!.x + name!.width).toBeLessThanOrEqual(warn!.x)
})

test('or write it: the Lead’s model draws a draft that is saved by the user alone, into the folder; a team’s default recipe is kept', async ({ page, request }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  await recipesTab(page)
  await page.getByLabel('The recipe in words').fill('First the spec writer, then the coder; ask me before it goes in.')
  await page.getByRole('button', { name: 'Make it a recipe' }).click()
  await expect(page.getByLabel('Recipe’s name')).toHaveValue(DRAWN)
  await expect(page.getByRole('button', { name: /^Write the spec/ })).toContainText('Spec writer')
  await expect(page.getByRole('status').filter({ hasText: 'Nothing is saved yet' })).toBeVisible()
  expect(((await (await request.get('/api/recipes')).json()) as { recipes: Named[] }).recipes.map(one => one.name)).not.toContain(DRAWN)
  // Kept in the folder: its .koloni/recipes, in git with it; said once.
  await page.getByLabel('Where it is kept').selectOption('folder')
  await page.getByRole('button', { name: 'Save recipe' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Saved in .koloni/ in this folder (kept in git).' })).toBeVisible()
  const file = path.join(RECIPES, 'spec-then-code.json')
  expect(existsSync(file)).toBe(true)
  expect(JSON.parse(readFileSync(file, 'utf8')).name).toBe(DRAWN)
  await expect(page.getByRole('button', { name: new RegExp(`^${DRAWN}`) })).toContainText('this folder’s')

  // A team's default recipe: one of KOLONİ's, kept over a reload.
  expect((await request.post('/api/teams', { headers: OWN, data: { name: TEAM } })).ok()).toBe(true)
  await page.reload()
  await page.getByLabel('Message').waitFor()
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  // (Its foot is the open team's: opened from its row.)
  await page.getByRole('region', { name: TEAM, exact: true }).getByRole('button', { name: new RegExp(`^${TEAM}`), expanded: false }).click()
  const pick = page.getByLabel(`${TEAM}'s default recipe`)
  expect(await pick.locator('option').allTextContents()).not.toContain(DRAWN) // a folder's own is not every folder's
  await pick.selectOption({ label: 'Bugfix' })
  await expect(pick).toHaveValue(/.+/)
  const team = ((await (await request.get('/api/teams')).json()) as (Named & { default_recipe_id: string | null })[]).find(one => one.name === TEAM)
  const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: Named[] }
  expect(team?.default_recipe_id).toBe(recipes.find(one => one.name === 'Bugfix')?.id)
})
