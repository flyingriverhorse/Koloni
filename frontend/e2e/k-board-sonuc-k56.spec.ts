// K-board-sonuc and K-56 in the browser, in both themes: a Tester that called no tool and said a
// short line is tagged "did nothing" on its Board card; the day's words KOLONİ asked a model for,
// with no message, are on the Usage page as "KOLONİ itself".
import { expect, test } from './fixtures'
import { contrasts, OWN, openFold, openFreshConversation, rail, shot, setProject } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme a sub-agent that did nothing is tagged on the Board, and Usage has KOLONİ itself`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    // (The fake model's Tester, handed "hello ...", says its greeting and calls no tool.)
    const message = `Ask a sub-agent in the Tester role to do this: hello, board result ${theme}`
    // (Opened without asking: the card for a Tester that may run commands is not this spec's.)
    await setProject(page, { spawn_approval: 'never' })
    const opened = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })
    expect(opened.ok()).toBe(true)
    const lastRun = async () => (await (await page.request.get(`/api/conversations/${id}`)).json()).runs.at(-1)
    await page.getByLabel('Message').fill(message)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect.poll(async () => (await lastRun())?.status, { timeout: 20_000 }).toBe('completed')

    await rail(page, 'Board').click()
    // (By its title's id: a long title is cut on the card.)
    const card = page.getByRole('region', { name: 'Ended today' }).locator('li.board-card', { has: page.locator(`#board-title-${id}`) })
    const tester = card.locator('.board-agent', { hasText: 'Tester' })
    await expect(tester.locator('.status')).toHaveText('done')
    await expect(tester.locator('.tag')).toHaveText('did nothing')
    // Nothing of it failed: nothing to re-run.
    await expect(card.getByRole('button', { name: 'Re-run the ones that failed' })).toHaveCount(0)
    expect((await card.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(card, `k-board-sonuc-did-nothing-${theme}`)

    // The day in words: a request KOLONİ makes of a model with no message.
    const project = (await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.project_id
    const since = new Date(Date.now() - 3600_000).toISOString()
    const words = await page.request.post(`/api/projects/${project}/day/words`, { data: { since, conversation_id: id }, headers: OWN })
    expect(words.ok(), await words.text()).toBe(true)
    await rail(page, 'Usage').click()
    await page.getByLabel('Period').selectOption({ label: 'Today' })
    await openFold(page, 'Who started it')
    const itself = page.getByRole('table', { name: 'Usage by who sent the message' }).getByRole('row', { name: /^KOLONİ itself/ })
    await expect(itself).toBeVisible()
    // in no message, with the tokens its model reported
    await expect(itself.getByRole('cell').first()).toHaveText('0')
    await expect(page.getByRole('region', { name: 'Who started it' })).toContainText(/\d+ requests? by KOLONİ itself/)
    const fold = page.getByRole('region', { name: 'Who started it' })
    await shot(fold, `k56-usage-koloni-itself-${theme}`)
  })
