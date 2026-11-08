import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type Locator, test } from './fixtures'
import { OWN, openFreshConversation, settled, setProject, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// K-evrim on the canvas (the user's, 5 Nov): an Evolve of two rounds, played by the fake model - its first round one line,
// the second's Coders right under it in the team's frame. A card clicked with the mouse moving a few pixels was pinned
// where it stood: once a round folded above it, it stayed down, under and out of its frame.
const RECIPE = 'Evolve 2 rounds, tuval'
const MEASURE = 'measure_ev2.py'

test.afterEach(async ({ page, request }) => {
  await setProject(page, { measure_command: '' })
  for (const file of [MEASURE, 'ev2.py']) rmSync(path.join(PROJECT_DIR, file), { force: true })
  const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: { id: string; name: string }[] }
  for (const recipe of recipes) if (recipe.name === RECIPE) expect((await request.delete(`/api/recipes/${recipe.id}`, { headers: OWN })).ok()).toBe(true)
})

const rect = async (one: Locator) => (await one.boundingBox())!

test('Evolve’s rounds on the canvas: the first a line, the second under it in the frame - a card clicked with a jitter follows the layout', async ({ page, request }) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const id = await openFreshConversation(page, { leadWrites: false })
  writeFileSync(path.join(PROJECT_DIR, MEASURE), "print(len(open('ev2.py').read()))\n")
  await setProject(page, { spawn_approval: 'never', measure_command: `python ${MEASURE}` })
  const graph = {
    version: 1,
    steps: [{ id: 'build', name: 'Try it', who: { candidates: 'Coder', most: 2 } }],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
    loops: [{ from: 'build', to: 'build', rounds: 1 }],
  }
  expect((await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })).ok()).toBe(true)
  const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === RECIPE)
  const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
  const set = await request.patch(`/api/conversations/${id}`, {
    headers: OWN,
    data: { permission_mode: 'full_auto', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
  })
  expect(set.ok()).toBe(true)
  await page.getByLabel('Message').fill('evolve it, ev2')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Evolved.').last()).toBeVisible({ timeout: 60_000 })

  const line = page.locator('.react-flow__node-round')
  const frame = page.locator('.react-flow__node-team')
  const card = (name: string) => page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title, .node-chip-name', { hasText: new RegExp(`^${name}$`) }) })
  await expect(line).toHaveCount(1)
  await expect(line).toContainText('Round 1 · Coder, Coder 2')
  await expect(card('Coder')).toHaveCount(0)
  await settled(page)
  await shot(page, 'k-evrim-tuval-two-rounds')
  const inFrame = async (one: Locator) => {
    const [f, b] = [await rect(frame), await rect(one)]
    return b.x >= f.x - 1 && b.y >= f.y - 1 && b.x + b.width <= f.x + f.width + 1 && b.y + b.height <= f.y + f.height + 1
  }
  // Right under the line, in the frame.
  for (const name of ['Coder 3', 'Coder 4']) {
    expect(await inFrame(card(name)), name).toBe(true)
    expect((await rect(card(name))).y - ((await rect(line)).y + (await rect(line)).height)).toBeLessThan(30)
  }

  // Everything open: round 1's cards over round 2's. Coder 3 (its chip: a finished agent of the newest round) clicked with
  // the mouse moving 3 pixels, round 1 folded again: Coder 3 goes back up under the line, in its frame.
  await page.getByRole('button', { name: 'Expand all' }).click()
  await expect(card('Coder')).toHaveCount(1)
  await settled(page)
  const head = card('Coder 3')
  const at = await rect(head)
  await page.mouse.move(at.x + at.width / 2, at.y + 10)
  await page.mouse.down()
  await page.mouse.move(at.x + at.width / 2 + 3, at.y + 10, { steps: 3 })
  await page.mouse.up()
  await line.getByRole('button', { expanded: true }).click()
  await expect(card('Coder')).toHaveCount(0)
  await expect.poll(() => inFrame(card('Coder 3'))).toBe(true)
  expect((await rect(card('Coder 3'))).y - ((await rect(line)).y + (await rect(line)).height)).toBeLessThan(30)
  await shot(page, 'k-evrim-tuval-folded-again')
})
