import { expect, test } from './fixtures'
import { OWN, contrasts, e2eProject, openFreshConversation, shot } from './helpers'

// K-evrim: the project's measure command, set in Settings › This project; the ready "Evolve" recipe in Recipes - three Coders as candidates,
// a target of 80 - and its copy's target changed and saved. The backend is shared with the other specs: what is set here is put back.
const COPY = 'Evolve copy'
let project = ''

test.afterEach(async ({ request }) => {
  if (project) expect((await request.patch(`/api/projects/${project}`, { headers: OWN, data: { measure_command: '' } })).ok()).toBe(true)
  const { recipes } = (await (await request.get('/api/recipes')).json()) as { recipes: { id: string; name: string }[] }
  for (const recipe of recipes) if (recipe.name === COPY) expect((await request.delete(`/api/recipes/${recipe.id}`, { headers: OWN })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  test(`the measure command is set, and the ready Evolve recipe's copy takes another target (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    project = await e2eProject(page)

    // Project settings: the measure command, beside the test command, sent alone.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const settings = page.getByRole('form', { name: 'Project settings' })
    await settings.getByRole('button', { name: /^Checks/ }).click()
    // (its why behind ⓘ, describing the field)
    await expect(settings.getByLabel('Measure command')).toHaveAccessibleDescription(/^The last line of its output is a number from 0 to 100/)
    const sent = page.waitForRequest(r => r.method() === 'PATCH' && /\/api\/projects\/[^/]+$/.test(r.url()))
    await settings.getByLabel('Measure command').fill('python measure.py')
    await settings.getByRole('button', { name: 'Save' }).click()
    expect((await sent).postDataJSON()).toEqual({ measure_command: 'python measure.py' })
    expect((await settings.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.getByRole('button', { name: 'Close settings' }).click()

    // Recipes: the ready Evolve says what it is; read-only, so a copy takes the new target.
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('tab', { name: 'Recipes' }).click()
    const evolve = page.getByRole('button', { name: /^Evolve/ })
    await expect(evolve).toContainText('Try it three ways · Coder ×3 · target 80 (≤3 rounds)')
    await evolve.click()
    await page.getByRole('button', { name: /^Try it three ways/ }).click()
    const part = page.getByRole('complementary', { name: /^Recipe part/ })
    await expect(part.getByLabel('Target score')).toHaveValue('80')
    await shot(page, `k-evrim-ready-${theme}`)
    expect((await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.getByRole('button', { name: 'Copy it' }).click()
    await expect(page.getByLabel('Recipe’s name')).toHaveValue(COPY)
    await page.getByRole('button', { name: /^Try it three ways/ }).click()
    await part.getByLabel('Target score').fill('90')
    const saved = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/recipes'))
    await page.getByRole('button', { name: 'Save recipe' }).click()
    expect((await saved).ok()).toBe(true)
    await expect(page.getByRole('button', { name: new RegExp(`^${COPY}`) })).toContainText('Coder ×3 · target 90')
  })
