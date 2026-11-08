import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, settled, shot, setProject } from './helpers'

// The conditional recipe step (the user's, 28 Oct): the Quality team runs its ready Quality check. Its Tester finds
// nothing, so its Debugger - which runs only if the step before found a problem - is never opened: the strip says
// "skipped: no problem found", and the reviews run. Nothing leaves the machine: the fake model plays it.
const lowContrast = async (page: Page, selector: string) => (await page.locator(selector).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`Quality check whose tests pass skips its Debugger (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page, { leadWrites: false })
    const quality = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Quality')
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: { permission_mode: 'full_auto', teams_mode: 'manual', teams: [{ team_id: quality!.id, recipe_id: null }] },
    })
    expect(set.ok()).toBe(true)

    await page.getByLabel('Message').fill(`quality check it, qc ${theme}`)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('Quality check is done: nothing found.').last()).toBeVisible({ timeout: 30_000 })
    const strip = page.locator('.team-frame').getByRole('list', { name: 'Quality check: its steps' })
    const steps = strip.getByRole('listitem')
    await expect(steps).toHaveText(['Run the tests ✓', 'Find and fix the cause · skipped: no problem found', 'All at once, wait for all ✓', 'Report ✓'])
    await expect(steps.nth(1)).toHaveClass(/team-step-unmet/)
    await settled(page)
    await expect(steps.nth(1)).toHaveAttribute('title', 'Find and fix the cause · skipped: no problem found')
    await shot(page, `84k-debugger-skipped-${theme}`)
    expect(await lowContrast(page, '.team-head')).toEqual([])
  })
}
