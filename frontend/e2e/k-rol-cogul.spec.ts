import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, settled, shot, setProject } from './helpers'

// K-rol-cogul: a recipe's role step draws "at most 2" Coders. In a run the Lead splits the work in two, a Coder a part, in one
// reply - both open at once, the step is done once both are, and the strip says "Coder ×2"; the editor's step says "At most 2".
// Nothing leaves the machine: the fake model plays it.
const RECIPE = 'Two coders rc'
const lowContrast = async (page: Page, selector: string) => (await page.locator(selector).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

test.afterEach(async ({ request }) => {
  const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: { id: string; name: string }[] }
  for (const recipe of recipes) if (recipe.name === RECIPE) expect((await request.delete(`/api/recipes/${recipe.id}`, { headers: OWN })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const) {
  test(`a step of at most two Coders opens two at once, and the strip and the editor say so (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page, { leadWrites: false })
    const graph = {
      version: 1,
      steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder', most: 2 } }],
      ends: [{ id: 'end', then: 'report' }],
      arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
    }
    const made = await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    expect(made.ok()).toBe(true)
    const recipe = (await made.json()) as { id: string }
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: { permission_mode: 'full_auto', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe.id }] },
    })
    expect(set.ok()).toBe(true)

    await page.getByLabel('Message').fill(`split it by the recipe, rc ${theme}`)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('Both parts are done.').last()).toBeVisible({ timeout: 30_000 })
    const steps = page.locator('.team-frame').getByRole('list', { name: `${RECIPE}: its steps` }).getByRole('listitem')
    await expect(steps).toHaveText(['Build it · Coder ×2 ✓', 'Report ✓'])
    await settled(page)
    await shot(page, `k-rol-cogul-strip-${theme}`)
    expect(await lowContrast(page, '.team-head')).toEqual([])

    // The editor: its step's "At most" field, and its card.
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('tab', { name: 'Recipes' }).click()
    await page.getByRole('button', { name: new RegExp(`^${RECIPE}`) }).click()
    await page.getByRole('button', { name: /^Build it/ }).click()
    await expect(page.getByRole('complementary', { name: /^Recipe part/ }).getByLabel('At most of its role', { exact: true })).toHaveValue('2')
    await expect(page.getByRole('button', { name: /^Build it/ })).toContainText('Coder, up to 2')
    await shot(page, `k-rol-cogul-editor-${theme}`)
    expect(await lowContrast(page, '.paged')).toEqual([])
  })
}
