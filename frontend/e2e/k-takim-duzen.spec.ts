import os from 'node:os'
import path from 'node:path'
import { expect, type Locator, type Page, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, settled, setProject } from './helpers'

// K-takim-duzen: the roles in seven categories on the Agents page - Data, ML and Ops after Build - and the ready recipe
// Model change (the ML team's default until 0.1.10; a team's recipe in Manual now), run with the fake model: the Data
// scientist plans, the experts' step is skipped (none has learned - the strip says so), the ML engineer builds, the Model
// evaluator compares the metrics (T3, 0195: no Tester or Reviewer step of its own - KOLONİ's Checks run the tests).
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'td-shots')
const shot = (target: Page | Locator, name: string) => target.screenshot({ path: path.join(SHOTS, `${name}.png`) })
const lowContrast = async (target: Locator) => (await target.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`the roles in seven categories, and a team runs by Model change (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page, { leadWrites: false })

    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(
      t => t.name === 'Web app',
    )
    const recipes = (await (await request.get('/api/recipes')).json()) as { recipes: { id: string; name: string }[] }
    const modelChange = recipes.recipes.find(r => r.name === 'Model change')
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: {
        permission_mode: 'full_auto',
        teams_mode: 'manual',
        teams: [{ team_id: web!.id, recipe_id: modelChange!.id }],
      },
    })
    expect(set.ok()).toBe(true)
    await page.getByLabel('Message', { exact: true }).fill(`model change it, mc ${theme}`)
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    const strip = page.locator('.team-frame').getByRole('list', { name: 'Model change: its steps' })
    await expect(strip.getByRole('listitem')).toHaveText(
      [
        'Plan the experiment ✓',
        'Experts review the plan · skipped: no expert has learned yet',
        'Build it ✓',
        'Compare the metrics ✓',
        /^You/,
      ],
      { timeout: 30_000 },
    )
    await settled(page)
    await shot(page, `td-model-change-${theme}`)
    expect(await lowContrast(page.locator('.team-head'))).toEqual([])

    // (Tall enough for every category in one shot.)
    await page.setViewportSize({ width: 1440, height: 2400 })
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    const library = page.getByRole('complementary', { name: 'Roles' })
    const groups = library.getByRole('region')
    await expect(groups.getByRole('heading')).toHaveText([
      /^Plan/,
      /^Build/,
      /^Data/,
      /^ML/,
      /^Ops/,
      /^Check/,
      /^Write & keep up/,
    ])
    for (const [group, role] of [
      ['Data', 'Data engineer'],
      ['ML', 'Data scientist'],
      ['ML', 'ML engineer'],
      ['Ops', 'MLOps engineer'],
      ['Ops', 'DevOps'],
      ['Check', 'Model evaluator'],
    ])
      await expect(
        library.getByRole('region', { name: group, exact: true }).getByRole('button', { name: new RegExp(`^${role}`) }),
      ).toBeVisible()
    await shot(library, `td-categories-${theme}`)
    expect(await lowContrast(library)).toEqual([])
  })
}
