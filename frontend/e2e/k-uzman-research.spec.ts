import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, dropKnowledge, e2eProject, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// K-uzman part 2: an expert that researches a topic. Its learning is laid down as one would have left it - the e2e's
// app reads only public addresses, and a search would leave this machine - and its row on the Knowledge page shows it
// (K-bilgi E): each entry's label beside its source, what was kept from answering, the version the documents are of,
// and the pages the search found, one of which is taken off its list. What a spec makes it takes away.
const KEPT = path.join(PROJECT_DIR, '.koloni', 'knowledge', 'hooks')
const SOURCES = ['research: pay webhooks']
const FOUND = 'https://blog.example.com/pay-webhooks'
const GUIDE = [
  '## What it offers',
  '- `constructEvent()` checks a webhook · https://docs.example.com/v2/hooks · official',
  '- Webhooks are retried for 3 days · https://docs.example.com/v2/hooks · official',
  `- conflict: retries stop after 3 or 5 days · ${FOUND} · unsure`,
  '',
  '## Found while answering',
  '- Retries back off exponentially · https://forum.example.com/t/2 · single source',
].join('\n')
type Named = { id: string; name: string }

test.afterEach(async ({ request }) => {
  for (const role of (await (await request.get('/api/roles')).json()) as Named[])
    if (role.name === 'Hooks expert') expect((await request.delete(`/api/roles/${role.id}`, { headers: OWN })).ok()).toBe(true)
  await dropKnowledge(request, 'Hooks')
  rmSync(KEPT, { recursive: true, force: true })
})

const lowContrast = async (page: Page) => (await page.locator('.knowledge-page').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`a researching expert's Knowledge page row shows its labels, the version warning and the pages found (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    mkdirSync(KEPT, { recursive: true })
    writeFileSync(path.join(KEPT, 'guide.md'), `${GUIDE}\n`)
    writeFileSync(
      path.join(KEPT, 'learned.json'),
      JSON.stringify({
        learned_at: new Date().toISOString(),
        sources: SOURCES,
        removed: [],
        model: 'Fake · fake-model',
        pages: [
          { source: 'https://docs.example.com/v2/hooks', read: true, why: null, found: true },
          { source: FOUND, read: true, why: null, found: true },
          { source: 'https://forum.example.com/t/1', read: false, why: 'robots.txt asks not to', found: true },
        ],
        unread: 0,
        parts: [],
        guide_from: 2,
        cost: null,
        labels: { official: 2, 'single source': 1, unsure: 1 },
        added: [{ text: 'Retries back off exponentially', source: 'https://forum.example.com/t/2' }],
        version: { project: '1.4.2', docs: '2' },
      }),
    )
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    // (Before the page opens: it reads the roles as it starts.)
    // (K-bilgi: its knowledge on the project's Knowledge page, the role using it in full.)
    const pid = await e2eProject(page)
    const known = await page.request.post(`/api/projects/${pid}/knowledge`, { headers: OWN, data: { topic: 'Hooks', sources: SOURCES } })
    expect(known.ok()).toBe(true)
    const kid: string = (await known.json()).id
    const made = await page.request.post('/api/roles', {
      headers: OWN,
      data: { name: 'Hooks expert', description: 'Knows Pay webhooks.', tools: ['read_file', 'search'] },
    })
    expect(made.ok()).toBe(true)
    expect((await page.request.put(`/api/knowledge/${kid}/roles/${(await made.json()).id}`, { headers: OWN, data: { mode: 'full' } })).ok()).toBe(true)
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Knowledge', exact: true }).click()
    const hooks = page.locator('.knowledge-card').filter({ hasText: 'Hooks expert' })
    await hooks.getByRole('button', { name: /Hooks/ }).click()
    const panel = page.locator('.knowledge-page')
    await hooks.getByRole('tab', { name: 'Settings' }).click()

    await expect(panel.getByLabel('Sources')).toHaveValue('research: pay webhooks')
    await expect(panel.getByLabel(/Learn again weekly/)).not.toBeChecked()
    // (Not said when it was made: an expert of a topic to research may search while answering.)
    await expect(panel.getByLabel(/Agents may search the web/)).toBeChecked()
    await hooks.getByRole('tab', { name: 'Guide' }).click()
    await expect(panel.getByText(/Entries: 2 official, 1 single source, 1 unsure/)).toBeVisible()
    await expect(panel.getByText('Version: docs are for v2, the project has v1.4.2.')).toBeVisible()
    await hooks.getByRole('tab', { name: /^Pages/ }).click()
    await expect(panel.getByText('Pages: 2 read, 1 skipped')).toBeVisible()
    await panel.getByText('Found while answering: 1, each a single source').click()
    await expect(panel.getByRole('button', { name: 'Remove Retries back off exponentially' })).toBeVisible()
    await hooks.getByRole('tab', { name: 'Guide' }).click()
    await expect(panel.locator('.knowledge-guide')).toContainText('Webhooks are retried for 3 days · https://docs.example.com/v2/hooks · official')
    await shot(page, `k-uzman-research-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    // A page the search found, taken off its list: kept with the knowledge, and the guide is old until it learns again.
    await hooks.getByRole('tab', { name: /^Pages/ }).click()
    await panel.getByRole('button', { name: `Remove ${FOUND}` }).click()
    await expect(panel.getByText('Removed: Learn again to leave it out of the guide.')).toBeVisible()
    await hooks.getByRole('tab', { name: 'Guide' }).click()
    await expect(panel.getByText(/old: a page was removed from its sources since/)).toBeVisible()
    await hooks.getByRole('tab', { name: /^Pages/ }).click()
    await expect(panel.getByRole('button', { name: `Remove ${FOUND}` })).toHaveCount(0)
    const kept = (await (await page.request.get(`/api/knowledge/${kid}?project_id=${pid}`)).json()) as { knowledge: { removed: string[] } }
    expect(kept.knowledge.removed).toEqual([FOUND])
  })
}
