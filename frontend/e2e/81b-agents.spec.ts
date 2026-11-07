import { expect, type APIRequestContext, type Page, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, say, settled, shot } from './helpers'

// Slice 81b, 63b: the Agents page - the Lead's strip, every role once in the library by category (teams: 63a's spec);
// off roles stay in their group, muted; a role opens beside, read first, its teams marked. And the canvas node says the
// tier an agent ran at. Nothing leaves the machine: the fake model answers, and a Reviewer is opened on its balanced tier.
type Named = { id: string; name: string }
let local: { id: string; models: unknown[] }

const roles = async (request: APIRequestContext) => (await (await request.get('/api/roles')).json()) as (Named & { enabled: boolean })[]
const roleId = async (request: APIRequestContext, name: string) => (await roles(request)).find(r => r.name === name)!.id
const patch = async (request: APIRequestContext, name: string, data: object) =>
  expect((await request.patch(`/api/roles/${await roleId(request, name)}`, { headers: OWN, data })).ok()).toBe(true)

test.beforeEach(async ({ request }) => {
  local = (await (await request.get('/api/providers')).json()).find((p: Named) => p.name === 'Local')
  // The fake model is the balanced one: a role with no tier given for the job runs on it.
  expect((await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models: [{ name: 'fake-qwen', tier: 'balanced' }] } })).ok()).toBe(true)
  await patch(request, 'Translator', { enabled: false })
  await patch(request, 'Security reviewer', { tier: 'strongest' })
})

test.afterEach(async ({ request }) => {
  expect((await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models: local.models } })).ok()).toBe(true)
  for (const name of ['Translator', 'Security reviewer', 'DevOps']) {
    await patch(request, name, { enabled: true })
    expect((await request.post(`/api/roles/${await roleId(request, name)}/reset`, { headers: OWN })).ok()).toBe(true)
  }
})

/** Every line of every library row and team row is whole: none wider or taller than its box (a row widens, never cuts). */
const cutLines = (page: Page) =>
  page.locator('.lib-row-open, .team-toggle').evaluateAll(rows =>
    rows.flatMap(row => [...row.children].filter(line => line.scrollWidth > line.clientWidth + 1 || line.scrollHeight > line.clientHeight + 1).map(line => line.textContent)),
  )
const pageScrollsSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
const lowContrast = async (page: Page) => (await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`the Agents page by kind of work, a role opened beside, the tier on the node (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)

    // A Reviewer is opened with no tier given: its node names its model; the tier is in the side panel (the user's, 5 Nov).
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    const reviewerNode = page.locator('.react-flow__node-agent').filter({ hasText: 'Reviewer' })
    await expect(reviewerNode.locator('.node-where')).toHaveText(' · Local · fake-qwen')
    await expect(reviewerNode).not.toContainText('balanced')
    await settled(page)
    await shot(page, `81b-node-${theme}`)

    // Teams & roles (slice 63b): the Lead's strip on top, every role once in the library by category, how many teams it is in.
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await expect(page.locator('.lead-strip')).toContainText('Lead — shown as Orchestrator · Talks with the user')
    await expect(page.locator('.lead-strip')).toContainText('Last: fake-qwen')
    const library = page.getByRole('complementary', { name: 'Roles' })
    for (const kind of ['Plan', 'Build', 'Data', 'ML', 'Ops', 'Check', 'Write & keep up']) await expect(library.getByRole('region', { name: kind, exact: true })).toBeVisible()
    const check = library.getByRole('region', { name: 'Check' })
    await expect(check.getByRole('button', { name: /^Reviewer/ })).toContainText('Reviewer4 teams')
    // off: muted in its own group, and counted
    const write = library.getByRole('region', { name: 'Write & keep up' })
    await expect(write.locator('.lib-row-off')).toHaveCount(1)
    await expect(write.locator('.lib-row-off')).toContainText('Translator')
    await expect(library.getByRole('button', { name: 'Off · 1' })).toBeVisible()
    // its switch turns a role off and on, at once (DevOps: in Ops since K-takim-duzen)
    const ops = library.getByRole('region', { name: 'Ops', exact: true })
    await ops.getByRole('switch', { name: 'DevOps on' }).click()
    await expect.poll(async () => (await roles(request)).find(r => r.name === 'DevOps')!.enabled).toBe(false)
    await expect(library.getByRole('button', { name: 'Off · 2' })).toBeVisible()
    await ops.getByRole('switch', { name: 'DevOps on' }).click()
    await expect.poll(async () => (await roles(request)).find(r => r.name === 'DevOps')!.enabled).toBe(true)
    expect(await cutLines(page)).toEqual([])
    expect(await pageScrollsSideways(page)).toBe(false)
    await shot(page, `81b-kind-1440-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    // A role opened beside: read first, its overview in words, the teams it is in marked; its history, the jobs with their conversations.
    await check.getByRole('button', { name: /^Reviewer/ }).click()
    const panel = page.getByRole('complementary', { name: 'Role Reviewer' })
    await expect(panel.getByLabel("Reviewer's category")).toHaveValue('check')
    await expect(panel).toContainText('Web app · Check')
    await expect(page.getByText(/^Reviewer is in 4 of \d+ teams · the others are faded while it is open$/)).toBeVisible()
    await expect(page.locator('.team-box-hit')).toHaveCount(4)
    await expect(panel).toContainText('Which modelOrchestrator · fast–strongest')
    await expect(panel.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(await cutLines(page)).toEqual([])
    await shot(page, `81b-panel-1440-${theme}`)
    expect(await lowContrast(page)).toEqual([])
    // 0.1.0-ui: what it did is the page's History tab
    await page.getByRole('tab', { name: 'History' }).click()
    await expect(page.getByRole('region', { name: 'Roles' })).toContainText('Reviewer')
    await page.getByRole('combobox', { name: 'Role' }).selectOption('Reviewer')
    await expect(page.getByRole('region', { name: 'Jobs' }).getByRole('row').nth(1)).toContainText('fake-qwen')
    await page.getByRole('tab', { name: 'Teams & roles' }).click()
    await panel.getByRole('tab', { name: 'Instructions' }).click()
    await expect(panel.getByRole('textbox', { name: 'Instructions' })).toHaveCount(0)
    await panel.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(panel.getByRole('textbox', { name: 'Instructions' })).toBeVisible()
    await panel.getByRole('button', { name: 'Cancel' }).click()
    // Its safety stops: last in its form's model part, folded and closed - no money limit.
    await panel.getByRole('tab', { name: 'Overview' }).click()
    await panel.getByRole('button', { name: 'Edit model' }).click()
    const stops = panel.locator('details.role-limits')
    await expect(stops).not.toHaveAttribute('open')
    await expect(panel.getByLabel('At most this many steps')).toBeHidden()
    await stops.locator('summary').click()
    await expect(panel.getByText('Stops one runaway agent of this role. Empty: KOLONİ’s own step limit.')).toBeVisible()
    await expect(panel.getByLabel('At most this many steps')).toBeVisible()
    await panel.getByLabel('At most this many steps').scrollIntoViewIfNeeded()
    await shot(page, `81b-safety-stops-${theme}`)
    await panel.getByRole('button', { name: 'Cancel' }).click()
    await panel.getByRole('button', { name: 'Close the role' }).click()

    // 1280 px: the library, the teams and the role beside; no line is cut and the page never scrolls sideways.
    await page.setViewportSize({ width: 1280, height: 800 })
    expect(await cutLines(page)).toEqual([])
    expect(await pageScrollsSideways(page)).toBe(false)
    await check.getByRole('button', { name: /^Reviewer/ }).click()
    expect(await cutLines(page)).toEqual([])
    expect(await pageScrollsSideways(page)).toBe(false)
    await shot(page, `81b-kind-1280-${theme}`)
    // Narrower: the library folds to "Roles ▸ N", a drawer over the teams.
    await page.setViewportSize({ width: 1100, height: 800 })
    await expect(library).toBeHidden()
    await page.getByRole('button', { name: /^Roles ▸ \d+$/ }).click()
    await expect(check.getByRole('button', { name: /^Reviewer/ })).toBeVisible()
    await shot(page, `81b-drawer-1100-${theme}`)
    expect(await lowContrast(page)).toEqual([])
    await page.getByRole('button', { name: 'Close the roles' }).click()
    await expect(library).toBeHidden()
    expect(await pageScrollsSideways(page)).toBe(false)
  })
}
