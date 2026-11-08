import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Locator, type Page } from './fixtures'
import { contrasts, openFreshConversation, OWN, rail, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// Slice 60c: the Tools and Memory pages read at a glance - in both themes, every text at a
// contrast of 4.5 or more, and neither scrolls sideways in a window 1024 px wide.
test.use({ viewport: { width: 1440, height: 900 } })

const sideways = (root: Element) => root.scrollWidth > root.clientWidth || document.documentElement.scrollWidth > window.innerWidth

async function readable(page: Page, root: Locator) {
  const all = await root.evaluate(contrasts)
  expect(all.length).toBeGreaterThan(15)
  expect(all.filter(piece => piece.ratio < 4.5)).toEqual([])
  await page.setViewportSize({ width: 1024, height: 900 })
  expect(await root.evaluate(sideways)).toBe(false)
  await page.setViewportSize({ width: 1440, height: 900 })
}

/** Everything in effect or waiting goes to Past, and the rules are emptied: the specs after start from an empty memory. */
async function clearMemory(request: APIRequestContext) {
  for (const project of (await (await request.get('/api/projects')).json()) as { id: string }[]) {
    const memory = await (await request.get(`/api/projects/${project.id}/memory`)).json()
    const ids = new Set<string>([...memory.proposals, ...memory.core, ...memory.journal].map((r: { id: string }) => r.id))
    for (const id of ids) await request.post(`/api/memory/${id}/reject`, { headers: OWN })
    await request.put(`/api/projects/${project.id}/rules`, { headers: OWN, data: { rules: '' } })
  }
}

for (const theme of ['light', 'dark'] as const) {
  test(`the Tools page with no server offers common servers, and a card only fills the form (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await rail(page, 'Tools').click()
    const cards = page.getByRole('region', { name: 'Start from a common server' }).getByRole('button')
    await expect(cards).toHaveCount(8)
    await expect(page.locator('form.tools-editor')).toBeHidden()
    // side by side, not a column of them
    const [first, second] = [await cards.nth(0).boundingBox(), await cards.nth(1).boundingBox()]
    expect(first!.y).toBe(second!.y)
    await expect(cards.first()).toContainText('May download @modelcontextprotocol/server-filesystem when it starts')
    // As its mockup (0.1.0-ui, layout A): across the page, the title and its Add menu on one row, the Servers tab's one line over the cards.
    const [title, add] = [await page.getByRole('heading', { name: 'Tools' }).boundingBox(), await page.getByRole('button', { name: 'Add', exact: true }).boundingBox()]
    expect(Math.abs(title!.y + title!.height / 2 - (add!.y + add!.height / 2))).toBeLessThan(4)
    expect((await page.locator('.tools-cards .tools-cards-grid').boundingBox())!.width).toBeGreaterThan(800)
    const lead = page.locator('#tools-panel-servers .tools-lead')
    expect((await lead.boundingBox())!.y).toBeLessThan((await cards.first().boundingBox())!.y)
    await expect(page.locator('.composer-warning')).toHaveCount(0)
    await shot(page, `60c-tools-${theme}`)
    // the line's ⓘ opened, so that what is behind it is measured too
    await lead.getByRole('button', { name: 'About this' }).click()
    await readable(page, page.locator('.tools-page'))

    // A card fills the form, and the token is left to you: nothing is added, started or downloaded.
    await page.getByRole('button', { name: /^GitHub/ }).click()
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('github')
    await expect(page.getByLabel('Value 1', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('Value 1', { exact: true })).toBeFocused()
    expect(await (await page.request.get('/api/mcp-servers')).json()).toEqual([])
    await readable(page, page.locator('.tools-page'))
  })

  test(`the Memory page: one search on top, what waits on one line, then four tabs with their counts (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await clearMemory(request)
    writeFileSync(path.join(PROJECT_DIR, 'settings.txt'), '# settings\nThe service listens on port 8123.\n')
    await openFreshConversation(page)
    const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
    const write = (data: object) => request.post(`/api/projects/${project.id}/memory`, { headers: OWN, data })
    try {
      expect((await write({ text: 'The service listens on port 8000.', about: 'port', file: 'settings.txt', start_line: 1 })).status()).toBe(201)
      expect((await write({ text: 'Commits are signed off.', about: 'commits' })).status()).toBe(201)
      const gone = await write({ text: 'The host is example.', about: 'host' })
      await request.post(`/api/memory/${(await gone.json()).id}/reject`, { headers: OWN })
      await request.put(`/api/projects/${project.id}/rules`, { headers: OWN, data: { rules: 'Sign every commit.' } })
      // The lead puts a note forward for the core.
      await page.getByLabel('Message').fill('note the port')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(page.getByRole('region', { name: 'Chat' }).getByText('Noted where the port is set. It waits for you.')).toBeVisible({ timeout: 15_000 })

      await rail(page, 'Memory').click()
      // Each tab with its count (History holds what the specs before put away too); Facts is open.
      // (The note would take the place of the fact on the port: it waits, and is not in the journal.)
      const memory = await (await request.get(`/api/projects/${project.id}/memory`)).json()
      expect(memory.past.length).toBeGreaterThan(0)
      const tabs = page.getByRole('tablist', { name: 'Memory' }).getByRole('tab')
      await expect(tabs).toHaveText(['Told 1', 'Facts 2', 'Notes 0', `History ${memory.decisions.length + memory.past.length}`])
      await expect(page.getByRole('tab', { name: /^Facts/ })).toHaveAttribute('aria-selected', 'true')
      // The search over everything first, then what waits on one line, then the tabs.
      const line = page.getByRole('button', { name: '● 1 fact waits for your word' })
      const search = (await page.getByRole('region', { name: 'Search', exact: true }).boundingBox())!
      const waits = (await line.boundingBox())!
      const tablist = (await page.getByRole('tablist', { name: 'Memory' }).boundingBox())!
      expect(search.y).toBeLessThan(waits.y)
      expect(waits.y).toBeLessThan(tablist.y)
      // Unfolded in place: what waits, with its Approve and Reject.
      await line.click()
      await expect(page.getByRole('region', { name: 'Waits for you' }).getByRole('button', { name: 'Approve', exact: true })).toBeVisible()
      await shot(page, `60c-memory-${theme}`)
      await page.getByRole('button', { name: '＋ Add a fact' }).click()
      await page.getByRole('region', { name: 'Add a fact' }).getByText('Subject, file and lines').click()
      await readable(page, page.locator('.memory-page'))
      // The other tabs read as well, in both widths.
      await page.getByRole('tab', { name: /^Told/ }).click()
      await expect(page.getByRole('region', { name: 'This project’s rules' }).getByLabel('Rules')).toHaveValue('Sign every commit.')
      await readable(page, page.locator('.memory-page'))
      await page.getByRole('tab', { name: /^History/ }).click()
      await readable(page, page.locator('.memory-page'))
    } finally {
      await clearMemory(request)
    }
  })
}
