import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, OWN, rail, roleRow, say, shot } from './helpers'

// Slice 61: KOLONİ's own tools on the Tools page. One switched off reads so on a role's tile, the role keeps it, and
// the next turn's agent is not offered it (the fake model says which web tools it was given). Nothing leaves the machine.
test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  // Put back as every other spec finds them: all on.
  for (const name of ['web_search', 'http_request', 'read_attachment'])
    expect((await request.put(`/api/builtin-tools/${name}`, { headers: OWN, data: { on: true } })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  test(`a built-in tool switched off on the Tools page is offered to no agent (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await say(page, 'which web tools, 61', 'Web tools: web_search, http_request.')

    await rail(page, 'Tools').click()
    await page.getByRole('tab', { name: /^Built-in/ }).click()
    const group = page.getByRole('region', { name: 'Built-in tools' })
    const web = group.getByRole('switch', { name: 'Search the web' })
    await expect(web).toBeChecked()
    await expect(group.getByRole('switch', { name: 'Read attached files' })).toBeChecked()
    await web.click()
    await expect(web).not.toBeChecked()
    await shot(group, `61-builtin-${theme}`)
    await shot(page, `61-tools-page-${theme}`)
    expect((await group.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // The role editor: the Lead's role still lists it, and its tile says it is off on the Tools page.
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await roleRow(page, 'Lead').click()
    const panel = page.getByRole('complementary', { name: 'Role Lead' })
    await panel.getByRole('tab', { name: 'Tools' }).click()
    const tile = panel.getByRole('button', { name: 'Search the web' })
    await expect(tile).toHaveAttribute('aria-pressed', 'true')
    await expect(tile).toContainText('off on the Tools page')
    await expect(panel.getByRole('button', { name: 'Web requests' })).not.toContainText('off on the Tools page')
    await shot(panel, `61-role-off-${theme}`)
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // The next turn: the Lead is not offered it.
    await rail(page, 'Canvas').click()
    await say(page, 'which web tools now, 61', 'Web tools: http_request.')
  })
