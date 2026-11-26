// Slice 67 in the browser: a conversation's title cut at a word's end; and the Conversations page
// grouped by day with a status filter.
import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme: the Conversations page groups and filters`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    await page
      .getByLabel('Message')
      .fill(`hello ${theme} - calc.html adinda basit bir hesap makinesi sayfasi yaz (HTML+CSS+JS tek dosya)`)
    await page.getByRole('button', { name: 'Send' }).click()
    const last = async () => (await (await page.request.get(`/api/conversations/${id}`)).json()).runs.at(-1)?.status
    await expect.poll(last, { timeout: 20_000 }).toBe('completed')
    const title = `hello ${theme} - calc.html adinda basit bir hesap makinesi…`

    // --- Conversations: under Today, found by "Done" (no "Waits for you": that is Ready for you's) ---
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Chats', exact: true }).click()
    const list = page.locator('.conv-page')
    const row = list.getByRole('button', { name: new RegExp(`^${title}`) })
    await expect(
      list.getByRole('region', { name: 'Today' }).getByRole('button', { name: new RegExp(`^${title}`) }),
    ).toBeVisible()
    await expect(row.locator('.conv-row-title')).toHaveText(title)
    await expect(list.getByLabel('Show', { exact: true }).getByRole('option', { name: 'Waits for you' })).toHaveCount(0)
    await list.getByLabel('Show', { exact: true }).selectOption({ label: 'Done' })
    await expect(row).toBeVisible()
    await list.getByLabel('Show', { exact: true }).selectOption({ label: 'All states' })
    expect((await list.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `67-conversations-${theme}`)

    // --- A chat made elsewhere (here: the API) is listed once Refresh conversations is pressed ---
    const { conversation } = await (await page.request.get(`/api/conversations/${id}`)).json()
    const made: string = (
      await (
        await page.request.post('/api/conversations', { data: { project_id: conversation.project_id }, headers: OWN })
      ).json()
    ).id
    await page.request.patch(`/api/conversations/${made}`, { data: { title: `made elsewhere ${theme}` }, headers: OWN })
    await list.getByRole('button', { name: 'Refresh conversations' }).click()
    await expect(list.getByRole('button', { name: new RegExp(`^made elsewhere ${theme}`) })).toBeVisible()
  })
}
