import { expect, type Page, test } from './fixtures'
import { contrasts, openFreshConversation, say } from './helpers'

// K-not-oda: a turn with teams has a notebook per team. One real turn gives a real record - with the note KOLONİ writes
// as the turn ends; the page is then handed that record with two teams' agents and their notes put in it, as the server
// gives them (no model plays a turn like that; k-canvas-lines does the same). Nothing leaves the machine.

type Json = Record<string, unknown>

/** The record of `id`'s chat with a Web app and a Docs team, and their notes, in its turn. */
async function twoTeams(page: Page, id: string): Promise<Json> {
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; runs: Json[]; conversation: Json; board_posts: Json[] }
  const [lead, run] = [snap.agents[0], snap.runs[0]]
  const agent = (aid: string, role: string, parent: string) => ({ ...lead, id: aid, role_name: role, name: role, parent_agent_id: parent, depth: parent === lead.id ? 1 : 2, status: 'completed', task: null })
  const note = (seq: number, agentId: string | null, content: string, team: [string, string] | null, everyone = false) => ({
    id: `n${seq}`,
    run_id: run.id,
    agent_id: agentId,
    content,
    seq,
    created_at: run.started_at,
    read_by: [],
    team_id: team?.[0] ?? null,
    team: team?.[1] ?? null,
    everyone,
    koloni: false,
  })
  const row = (team_id: string) => ({ team_id, recipe_id: null, picked_by: 'user', why: null, state: null })
  const [web, docs]: [string, string][] = [['web', 'Web app'], ['docs', 'Docs']]
  const L = lead.id as string
  return {
    ...snap,
    conversation: { ...snap.conversation, teams_mode: 'manual', teams: [row('web'), row('docs')] },
    agents: [lead, agent('wl', 'Web app lead', L), agent('wc', 'Coder', 'wl'), agent('dl', 'Docs lead', L)],
    board_posts: [
      note(1, 'wc', 'web/app.js is mine.', web),
      note(2, 'wl', 'The API is /v2 from now on.', web, true),
      note(3, 'dl', 'b.md waits for the API.', docs),
      note(4, null, 'Keep the words short.', null),
      { ...note(5, null, 'This turn is done. Done: Web app lead, Coder, Docs lead.', null), koloni: true, created_at: run.ended_at },
    ],
  }
}

for (const theme of ['light', 'dark'] as const) {
  test(`a turn with two teams has a notebook per team, and KOLONİ's note stands apart (${theme})`, async ({ page }, testInfo) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // (A tall chat: every team's notes in the shot.)
    await page.addInitScript(() => localStorage.setItem('koloni-chat-height', '0.96'))
    await page.setViewportSize({ width: 1440, height: 1000 })
    const id = await openFreshConversation(page)
    await say(page, 'hello, the notes of two teams', 'Hello! Ask me to read or change a file.')
    const record = await twoTeams(page, id)
    // The real turn did what it was asked with no agent: KOLONİ noted nothing of it.
    expect((await (await page.request.get(`/api/conversations/${id}`)).json()).board_posts).toEqual([])
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()

    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('tab', { name: /^Notes/ }).click()
    const groups = chat.getByRole('region')
    await expect(groups).toHaveCount(3)
    expect(await groups.evaluateAll(all => all.map(g => g.getAttribute('aria-label')))).toEqual(['For every team', 'Web app notes', 'Docs notes'])
    const [whole, web, docs] = [groups.nth(0), groups.nth(1), groups.nth(2)]
    await expect(web).toContainText('web/app.js is mine.')
    await expect(docs).toContainText('b.md waits for the API.')
    await expect(docs).not.toContainText('web/app.js')
    // A team lead's note for every team is marked; each team has a colour of its own.
    await expect(web.locator('.channel-message', { hasText: 'The API is /v2' }).getByText('for every team')).toBeVisible()
    const dot = async (group: typeof web) => group.locator('.team-dot').evaluate(el => getComputedStyle(el).backgroundColor)
    expect(await dot(web)).not.toEqual(await dot(docs))
    // KOLONİ's note: who wrote it, drawn apart, for the next turn; yours is not.
    const koloni = whole.locator('.channel-message', { hasText: 'This turn is done. Done:' })
    await expect(koloni).toHaveClass(/note-koloni/)
    await expect(koloni.locator('.channel-head')).toContainText('KOLONİ')
    await expect(koloni).toContainText('written as this work ended, for the next turn')
    await expect(whole.locator('.channel-message', { hasText: 'Keep the words short.' })).not.toHaveClass(/note-koloni/)
    // Every word of it reads in this theme.
    expect((await chat.locator('.msg-list').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    const file = testInfo.outputPath(`notes-two-teams-${theme}.png`)
    await chat.screenshot({ path: file })
    await testInfo.attach(`the Notes tab with two teams (${theme})`, { path: file, contentType: 'image/png' })
  })
}
