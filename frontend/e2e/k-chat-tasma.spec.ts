import { expect, test } from './fixtures'
import { openFreshConversation, say } from './helpers'

// The user's report, 4 Nov: in a chat 470-560px wide a finished sub-agent's folded report and KOLONİ's "What it did" line
// under it ran past the chat's right edge, and the message list scrolled sideways. One real turn gives a real record; the
// page is then handed it with two sub-agents' reports in it, as a CLI Lead's chat has them (no model plays such a turn).

type Json = Record<string, unknown>
const TASK = 'Project: ./ is the project folder (the notes app; standard library only). Make the docs match the server and add a test.'
const REPORTS = [
  ['dbg', 'Debugger', 'The docs now match the server, and python -m unittest discover -s tests passes with the new routes in it as well.', 'read 1 file, wrote 2 ("docs/api.md", "test_server_routes_with_a_rather_long_name.py"), ran 1 command, last the one that ran the whole suite'],
  ['tst', 'Tester', 'The full suite passes, the new test passes on its own, and nothing else in the notes app had to change for it.', 'read 0 files, wrote 0, ran 1 command, last tests/test_server_routes_with_a_rather_long_name.py run on its own'],
]

for (const theme of ['light', 'dark'] as const)
  test(`a finished sub-agent's report and what it did stay inside the chat: nothing scrolls sideways (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page)
    await say(page, 'hello, two sub-agents', 'Hello! Ask me to read or change a file.')
    const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; messages: Json[] }
    const lead = snap.agents[0]
    const answer = snap.messages.find(m => m.role === 'assistant')!
    const record = {
      ...snap,
      agents: [
        lead,
        ...REPORTS.map(([aid, name]) => ({ ...lead, id: aid, name, role_name: name, parent_agent_id: lead.id, depth: 1, status: 'completed', task: TASK, tool_call_id: `s-${aid}` })),
      ],
      tool_calls: [
        ...((snap.tool_calls as Json[]) ?? []),
        ...REPORTS.map(([aid, name], seq) => ({
          id: `s-${aid}`, run_id: answer.run_id, agent_id: lead.id, message_id: answer.id, origin: 'koloni', parent_call_id: null, outside_folder: null,
          why_asked: null, seq: 100 + seq, provider_call_id: `s-${aid}`, name: 'spawn_agent', arguments: JSON.stringify({ role: name, task: TASK }),
          status: 'succeeded', result: `${name} finished.`, started_at: answer.created_at, ended_at: answer.created_at,
        })),
      ],
      messages: [
        ...snap.messages,
        ...REPORTS.map(([aid, name, said, did]) => ({
          ...answer, id: `m-${aid}`, role: 'agent', agent_id: lead.id, from_agent_id: aid,
          content: `${name} finished.\n\n${said}\n\nMore of the report.\n\nWhat it did, from KOLONİ's record: ${did}.`,
        })),
      ],
    }
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByRole('button', { name: /^Debugger · done · The docs now match the server/ })).toBeVisible()
    await expect(chat.getByRole('button', { name: /^Tester · done · The full suite passes/ })).toBeVisible()
    // (The spawn rows, cut inside their box: measured below with the rest.)
    await expect(chat.locator('.tool-row', { hasText: 'Project: ./ is the project folder' })).toHaveCount(2)

    // (Its widths in the user's screenshots: wider than the chat is by itself, at most 480px.)
    for (const width of [470, 560]) {
      const style = await page.addStyleTag({ content: `.stage { --chat-w: ${width}px !important; }` })
      await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(width)
      const list = chat.locator('.msg-list')
      const { wide, past } = await list.evaluate(el => {
        const end = el.getBoundingClientRect().left + el.clientWidth
        return {
          wide: el.scrollWidth - el.clientWidth,
          past: [...el.querySelectorAll('.msg-from, .msg-from > *, .tool-run-what, .tool-row')]
            .filter(row => row.getBoundingClientRect().right > end + 1)
            .map(row => `${row.className}: ${row.textContent?.slice(0, 40)}`),
        }
      })
      expect(wide, `the list at ${width}px scrolls sideways by`).toBeLessThanOrEqual(1)
      expect(past, `rows past the list's end at ${width}px`).toEqual([])
      const sideways = await chat.evaluate(root =>
        [root, ...root.querySelectorAll('*')]
          .filter(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1)
          .map(el => el.className),
      )
      expect(sideways).toEqual([])
      // KOLONİ's record wraps, all of it in sight; the folded line cuts with an ellipsis.
      const did = chat.getByText(/^What it did, from KOLONİ's record: read 1 file/)
      await expect(did).toContainText('last the one that ran the whole suite.')
      expect(await did.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().height > 30)).toBe(true)
      await style.evaluate(el => el.remove())
    }
  })
