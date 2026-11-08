// B-174: with a turn at work, a trigger on, Stop everything and the bell in it, the top bar keeps to one line down to
// 1000 px: the title gives way (cut short, never gone) and the lesser buttons show their icons alone. B-180: held too
// (Stop everything says "Held" alone there). B-195: at 1283 and 1210 px it took two lines while the turn waited.
import { expect, test } from './fixtures'
import { OWN, e2eProject, openFreshConversation } from './helpers'

for (const [width, held] of [
  [1283, false],
  [1210, false],
  [1171, false],
  [1000, false],
  [1147, true],
  [1000, true],
] as const) {
  test(`at ${width} px, with a turn at work${held ? ', held' : ''}, the top bar is one line and its title is seen`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize({ width, height: 800 })
    const project = await e2eProject(page)
    const its = await (await page.request.post('/api/conversations', { data: { project_id: project }, headers: OWN })).json()
    const made = await page.request.post(`/api/projects/${project}/triggers`, {
      headers: OWN,
      data: { name: `b174 ${width}`, kind: 'webhook', conversation_id: its.id, message: 'Nothing: it is never called.' },
    })
    expect(made.status()).toBe(201)
    const trigger: { id: string } = await made.json()
    try {
      // (Your own messages still run while held.)
      if (held) expect((await page.request.post('/api/hold', { headers: OWN })).ok()).toBe(true)
      // The bell stands from the first note: a turn out of sight ends (the Board is answered here for it).
      let first: number | null = null
      await page.route('**/api/board', async route => {
        const real = await (await route.fetch()).json()
        first ??= Date.now()
        const status = Date.now() - first < 3000 ? 'running' : 'completed'
        const turn = { id: 'b174', status, started_at: 't', ended_at: null, agents: 1, provider_name: null, model_id: null, tokens: null, plan_waits: false }
        const elsewhere = { conversation_id: 'out-of-sight', title: 'Elsewhere', agents: [], merges_pending: 0, turn, project_id: null }
        await route.fulfill({ json: { ...real, conversations: [...real.conversations, elsewhere] } })
      })
      await openFreshConversation(page)
      // (Ends in "slowly": the scripted Lead asks to run a command, and its turn waits for the answer.)
      const title = `A turn at work in a bar ${width} px wide, run it slowly`
      await page.getByLabel('Message').fill(title)
      await page.getByRole('button', { name: 'Send' }).click()
      const bar = page.locator('.topbar')
      await expect(bar.locator('[data-run="waiting_approval"]')).toBeVisible({ timeout: 15_000 })
      await expect(bar.getByRole('button', { name: /^Notifications/ })).toBeVisible({ timeout: 15_000 })
      await expect(bar.getByRole('button', { name: /trigger/ })).toBeVisible()
      await expect(bar.getByRole('button', { name: held ? 'Held · Resume' : 'Stop everything' })).toBeVisible()

      // one line: everything in it is as high up as Help, and the bar no higher than a bar of one line
      const help = (await bar.getByRole('button', { name: 'Help' }).boundingBox())!
      const tops = await bar.locator('.topbar-title > *, .topbar-right > *, .topbar-right > * > *').evaluateAll(all =>
        all.filter(el => el.getClientRects().length > 0).map(el => [el.className, el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2] as const),
      )
      for (const [name, middle] of tops) expect(Math.abs(middle - (help.y + help.height / 2)), String(name)).toBeLessThan(6)
      expect((await bar.boundingBox())!.height).toBe(52)
      // the title is there, cut short where it must be
      const shown = page.locator('.topbar-title strong')
      await expect(shown).toHaveText(title)
      expect(await shown.evaluate(el => el.clientWidth)).toBeGreaterThanOrEqual(60)

      // (The command is not run.)
      await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
    } finally {
      // (A Board read still being answered as the test ends is let go, not a failure.)
      await page.unrouteAll({ behavior: 'ignoreErrors' })
      // (The backend is shared with the specs after this one: nothing is left held.)
      if (held) expect((await page.request.post('/api/hold/resume', { headers: OWN })).ok()).toBe(true)
      await page.request.delete(`/api/triggers/${trigger.id}`, { headers: OWN })
    }
  })
}

// B-195 (live, 1283 px): two plans' use beside a turn that waits and a trigger took the bar to two lines from 1200 px
// up; there the plans take their strip under it (K-dar-cubuk), and the rest of the bar keeps to one line.
test('at 1283 px, with two plans read and a turn that waits, the plans are in their strip and the bar is one line', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1283, height: 800 })
  const plan = (id: string, name: string, kind: string, position: number) => ({
    id, name, kind, base_url: null, default_model: 'x', executable: null, mode: null, options: null, for_agents: false, note: null, models: [],
    only_listed: false, max_running: null, plan: true, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position,
    created_at: 't', updated_at: 't',
  })
  // (On the page only: no turn runs on them.)
  await page.route('**/api/providers', async route => {
    if (route.request().method() !== 'GET') return route.fallback()
    const real = await (await route.fetch()).json()
    await route.fulfill({ json: [...real, plan('b195c', 'Claude Code', 'claude_cli', 90), plan('b195x', 'Codex', 'codex_cli', 91)] })
  })
  await page.route('**/api/providers/b195*/limits', route =>
    route.fulfill({ json: { windows: [{ minutes: 300, name: '5h', used_percent: 85, stale: false, resets_at: null }], read_at: null } }),
  )
  const project = await e2eProject(page)
  const its = await (await page.request.post('/api/conversations', { data: { project_id: project }, headers: OWN })).json()
  const trigger: { id: string } = await (
    await page.request.post(`/api/projects/${project}/triggers`, {
      headers: OWN,
      data: { name: 'b195', kind: 'webhook', conversation_id: its.id, message: 'Nothing: it is never called.' },
    })
  ).json()
  try {
    await openFreshConversation(page)
    await page.getByLabel('Message').fill('A turn at work in a bar 1283 px wide, run it slowly')
    await page.getByRole('button', { name: 'Send' }).click()
    const bar = page.locator('.topbar')
    await expect(bar.locator('[data-run="waiting_approval"]')).toBeVisible({ timeout: 15_000 })
    await expect(bar.getByRole('button', { name: /^Plan use: / })).toBeVisible({ timeout: 15_000 })
    const help = (await bar.getByRole('button', { name: 'Help' }).boundingBox())!
    const tops = await bar.locator('.topbar-title > *, .topbar-right > :not(.plan-use)').evaluateAll(all =>
      all.filter(el => el.getClientRects().length > 0).map(el => [el.className, el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2] as const),
    )
    for (const [name, middle] of tops) expect(Math.abs(middle - (help.y + help.height / 2)), String(name)).toBeLessThan(6)
    // (the strip: under the line)
    expect((await bar.locator('.plan-use').boundingBox())!.y).toBeGreaterThan(help.y + help.height)
    await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
  } finally {
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    await page.request.delete(`/api/triggers/${trigger.id}`, { headers: OWN })
  }
})
