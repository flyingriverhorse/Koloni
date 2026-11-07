// Slice 67 in the browser: a conversation's title cut at a word's end; the Conversations page
// grouped by day with a status filter; and the Triggers page's ready-made triggers, which only
// fill the form - nothing is made until it is added.
import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme: the Conversations page groups and filters, and a ready-made trigger fills the form`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    await page.getByLabel('Message').fill(`hello ${theme} - calc.html adinda basit bir hesap makinesi sayfasi yaz (HTML+CSS+JS tek dosya)`)
    await page.getByRole('button', { name: 'Send' }).click()
    const last = async () => (await (await page.request.get(`/api/conversations/${id}`)).json()).runs.at(-1)?.status
    await expect.poll(last, { timeout: 20_000 }).toBe('completed')
    const title = `hello ${theme} - calc.html adinda basit bir hesap makinesi…`

    // --- Conversations: under Today, found by "Done" (no "Waits for you": that is Ready for you's) ---
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Chats', exact: true }).click()
    const list = page.locator('.conv-page')
    const row = list.getByRole('button', { name: new RegExp(`^${title}`) })
    await expect(list.getByRole('region', { name: 'Today' }).getByRole('button', { name: new RegExp(`^${title}`) })).toBeVisible()
    await expect(row.locator('.conv-row-title')).toHaveText(title)
    await expect(list.getByLabel('Show', { exact: true }).getByRole('option', { name: 'Waits for you' })).toHaveCount(0)
    await list.getByLabel('Show', { exact: true }).selectOption({ label: 'Done' })
    await expect(row).toBeVisible()
    await list.getByLabel('Show', { exact: true }).selectOption({ label: 'All states' })
    expect((await list.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `67-conversations-${theme}`)

    // --- A chat made elsewhere (here: the API) is listed once Refresh conversations is pressed ---
    const { conversation } = await (await page.request.get(`/api/conversations/${id}`)).json()
    const made: string = (await (await page.request.post('/api/conversations', { data: { project_id: conversation.project_id }, headers: OWN })).json()).id
    await page.request.patch(`/api/conversations/${made}`, { data: { title: `made elsewhere ${theme}` }, headers: OWN })
    await list.getByRole('button', { name: 'Refresh conversations' }).click()
    await expect(list.getByRole('button', { name: new RegExp(`^made elsewhere ${theme}`) })).toBeVisible()

    // --- Triggers: a card fills the form; nothing is made until "Add trigger" ------------------
    const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
    const ids = async () => ((await (await request.get(`/api/projects/${project.id}/triggers`)).json()) as { id: string }[]).map(one => one.id)
    const had = await ids()
    try {
      await rail(page, 'Triggers').click()
      const triggers = page.locator('.triggers-page')
      // The ready-made ones are in "New trigger"'s list, with a blank one.
      const ready = page.getByRole('menu', { name: 'New trigger' })
      const link = triggers.getByRole('button', { name: 'New trigger' })
      if (had.length === 0) await expect(triggers.getByText('No trigger yet. Nothing in this project starts by itself.')).toBeVisible()
      await link.click()
      await expect(ready.getByRole('menuitem')).toHaveCount(5)
      await expect(ready.getByRole('menuitem', { name: /^Every Friday at 17:00/ })).toContainText('Fridays at 17:00, the first on the next Friday.')
      expect((await triggers.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      await shot(page, `67-triggers-${theme}`)

      // The Friday one: a time of day on chosen days, Friday ticked; cancelled, nothing made.
      await ready.getByRole('menuitem', { name: /^Every Friday at 17:00/ }).click()
      let form = page.getByRole('form', { name: 'New trigger' })
      await expect(form.getByLabel('Time', { exact: true })).toHaveValue('17:00')
      await expect(form.getByLabel('Days', { exact: true })).toHaveValue('chosen')
      const week = form.getByRole('group', { name: 'On these days' })
      await expect(week.getByRole('checkbox')).toHaveCount(7)
      await expect(week.getByRole('checkbox', { name: 'Friday' })).toBeChecked()
      await expect(form.getByLabel('May change files', { exact: true })).not.toBeChecked()
      await expect(form.getByLabel('May open sub-agents', { exact: true })).toHaveValue('0')
      const when = form.locator('fieldset.trigger-leave').first()
      expect((await when.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      await when.scrollIntoViewIfNeeded()
      await shot(page, `67-trigger-days-${theme}`)
      expect(await ids()).toEqual(had)
      await form.getByRole('button', { name: 'Cancel' }).click()
      await expect(form).toHaveCount(0)
      expect(await ids()).toEqual(had)

      // The morning one, added: now it is made, a row of its own.
      await link.click()
      await ready.getByRole('menuitem', { name: /^Every morning/ }).click()
      form = page.getByRole('form', { name: 'New trigger' })
      await form.getByRole('button', { name: 'Add trigger' }).click()
      await expect(form).toHaveCount(0)
      await expect.poll(async () => (await ids()).length).toBe(had.length + 1)
      await expect(triggers.getByRole('article', { name: 'Every morning: summarise the work since the last working day' }).first()).toBeVisible()
      await expect(ready).toHaveCount(0)
      await shot(page, `67-triggers-with-one-${theme}`)
    } finally {
      // What this spec made goes: a weekday 09:00 trigger left on could start a turn in another spec.
      for (const made of (await ids()).filter(one => !had.includes(one))) {
        expect((await request.delete(`/api/triggers/${made}`, { headers: OWN })).ok()).toBe(true)
      }
      expect(await ids()).toEqual(had)
    }
  })
}
