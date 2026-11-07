import { existsSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, settled, shot, setProject } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// Slice 84b-2: a chat team runs its recipe. In Manual, Web app with a one-step recipe: the Lead opens the step's Coder,
// whose work waits in the recipe's copy; on the canvas the team's frame (its step strip) and "Ready for you" meet,
// NEEDS YOU; Take in takes the work in, and the node says so. Nothing leaves the machine: the fake model plays it.
// (Auto-edit: at Full auto a recipe's Ask me is the Lead's and its work is taken in by itself, K-fullauto-sorma 2;
// these specs are about the cards, which stay below Full auto.)
const RECIPE = 'Build only 84b2'
const lowContrast = async (page: Page, selector: string) => (await page.locator(selector).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`a small recipe runs to Ready for you, and Take in takes it in (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const file = path.join(PROJECT_DIR, `recipe84-${theme}.txt`)
    rmSync(file, { force: true })
    const id = await openFreshConversation(page, { leadWrites: false })

    // One step, by the Coder, then "ask me, then in" (made once: the e2e's KOLONİ is shared by its specs).
    const graph = {
      version: 1,
      steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder' } }],
      ends: [{ id: 'end', then: 'in' }],
      arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
    }
    await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === RECIPE)
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: { permission_mode: 'auto_edit', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
    })
    expect(set.ok()).toBe(true)

    await page.getByLabel('Message').fill(`build it by the recipe, 84b2 ${theme}`)
    await page.getByRole('button', { name: 'Send' }).click()
    const ready = page.locator('.ready-node')
    await expect(ready).toContainText('NEEDS YOU', { timeout: 20_000 })
    // The team's frame, its recipe's step strip, and the work kept out of the project until Take in.
    const frame = page.locator('.team-frame')
    await expect(frame).toContainText('Web app')
    await expect(frame.getByRole('list', { name: `${RECIPE}: its steps` })).toContainText('Build it ✓')
    await expect(ready).toContainText('Nothing is in the project yet.')
    expect(existsSync(file)).toBe(false)
    // The whole turn is in view at 1440×900: the Ready node too, not cut at the canvas's edge.
    await settled(page)
    const [shown, canvas] = [await ready.boundingBox(), await page.locator('.canvas-flow').boundingBox()]
    expect(shown!.x).toBeGreaterThanOrEqual(canvas!.x)
    expect(shown!.y).toBeGreaterThanOrEqual(canvas!.y)
    expect(shown!.x + shown!.width).toBeLessThanOrEqual(canvas!.x + canvas!.width)
    expect(shown!.y + shown!.height).toBeLessThanOrEqual(canvas!.y + canvas!.height)
    await shot(page, `84b2-ready-for-you-${theme}`)
    expect(await lowContrast(page, '.ready-node')).toEqual([])
    expect(await lowContrast(page, '.team-head')).toEqual([])

    // Answered in the chat's one list (K-bekleyenler): the node opens it.
    await ready.getByRole('button', { name: 'Open the list →' }).click()
    await page.getByRole('region', { name: 'Ready to take in' }).getByRole('button', { name: 'Take in' }).click()
    await page.getByRole('tab', { name: 'Chat' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('The recipe is done and in the project.').last()).toBeVisible({ timeout: 20_000 })
    await expect(ready).toContainText('In the project ✓')
    expect(existsSync(file)).toBe(true)
    await shot(page, `84b2-in-the-project-${theme}`)
    rmSync(file, { force: true })

    // B-107: the chat's teams changed after the turn do not redraw it - here, and loaded afresh.
    const none = await request.patch(`/api/conversations/${id}`, { headers: OWN, data: { teams_mode: 'none', teams: [] } })
    expect(none.ok()).toBe(true)
    for (const afresh of [false, true]) {
      if (afresh) await page.reload()
      await expect(page.getByRole('button', { name: /No teams/ })).toBeVisible()
      await expect(frame).toContainText('Web app')
      await expect(ready).toContainText('In the project ✓')
    }
  })
}

// Slice 84e: a recipe's Room step - its roles meet in one room, drawn in the team's frame; the step strip says Room;
// the room's work waits in the recipe's copy until Take in.
test('a Room step meets in the team frame, and its work comes in only with Take in', async ({ page, request }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const file = path.join(PROJECT_DIR, 'recipe84e-light.txt')
  rmSync(file, { force: true })
  const id = await openFreshConversation(page, { leadWrites: false })
  const name = 'Meet only 84e'
  const graph = {
    version: 1,
    steps: [{ id: 'meet', name: 'Design meeting', who: { room: ['Coder', 'Reviewer'] } }],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [{ from: 'start', to: 'meet' }, { from: 'meet', to: 'end' }],
  }
  await request.post('/api/recipes', { headers: OWN, data: { name, graph } })
  const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === name)
  const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
  await setProject(page, { spawn_approval: 'never' })
  const set = await request.patch(`/api/conversations/${id}`, {
    headers: OWN,
    data: { permission_mode: 'auto_edit', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
  })
  expect(set.ok()).toBe(true)

  await page.getByLabel('Message').fill('meet by the recipe, 84e light')
  await page.getByRole('button', { name: 'Send' }).click()
  const ready = page.locator('.ready-node')
  await expect(ready).toContainText('NEEDS YOU', { timeout: 20_000 })
  const frame = page.locator('.team-frame')
  await expect(frame.getByRole('list', { name: `${name}: its steps` })).toContainText('Design meetingRoom ✓')
  expect(existsSync(file)).toBe(false)
  // The room's box inside the team's frame.
  const [box, around] = [await page.locator('.react-flow__node-room').boundingBox(), await frame.boundingBox()]
  expect(box!.y).toBeGreaterThanOrEqual(around!.y)
  expect(box!.y + box!.height).toBeLessThanOrEqual(around!.y + around!.height)
  // (AC: the room opened in its own window over the canvas, and says it is over there; × puts it away.)
  const room = page.getByRole('dialog', { name: /^Room: Meet 84e light/ })
  await expect(room.getByText(/^done/)).toBeVisible()
  await room.getByRole('button', { name: 'Close the room' }).click()
  await expect(room).toHaveCount(0)
  await shot(page, '84e-room-step')
  await ready.getByRole('button', { name: 'Open the list →' }).click()
  await page.getByRole('region', { name: 'Ready to take in' }).getByRole('button', { name: 'Take in' }).click()
  await expect(ready).toContainText('In the project ✓', { timeout: 20_000 })
  expect(existsSync(file)).toBe(true)
  rmSync(file, { force: true })
})

// B-99: the recipe's own questions are in the chat, under the call that opened the step's agent, and answered there:
// its Ask me step's "Go on?", then "Take the work into the project?".
test('a recipe’s Ask me and its Take in are answered in the chat', async ({ page, request }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const file = path.join(PROJECT_DIR, 'recipe84-askme.txt')
  rmSync(file, { force: true })
  const id = await openFreshConversation(page, { leadWrites: false })
  const name = 'Ask me 84b2'
  const graph = {
    version: 1,
    steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder' }, ask_me: true }],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
  }
  await request.post('/api/recipes', { headers: OWN, data: { name, graph } })
  const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === name)
  const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
  await setProject(page, { spawn_approval: 'never' })
  const set = await request.patch(`/api/conversations/${id}`, {
    headers: OWN,
    data: { permission_mode: 'auto_edit', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
  })
  expect(set.ok()).toBe(true)

  await page.getByLabel('Message').fill('build it by the recipe, 84b2 askme')
  await page.getByRole('button', { name: 'Send' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  // (A title of KOLONİ's own, its words whole under it: sample A.)
  await expect(chat.getByText(`Web app: Build it is done. Go on with the ${name} recipe?`)).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByText('Go on with the recipe?', { exact: true })).toBeVisible()
  await chat.getByRole('button', { name: 'Go on' }).click()
  // (KOLONİ's Ready for you card, one line in the chat: K-hazir-satir.)
  await expect(chat.getByText(/^Teams' work is ready/)).toBeVisible({ timeout: 20_000 })
  expect(existsSync(file)).toBe(false)
  await chat.getByRole('button', { name: 'Take in' }).click()
  await expect(chat.getByText('The recipe is done and in the project.').last()).toBeVisible({ timeout: 20_000 })
  expect(existsSync(file)).toBe(true)
  rmSync(file, { force: true })
})
