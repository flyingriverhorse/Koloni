import { expect, type Locator, test } from './fixtures'
import { openFreshConversation, say } from './helpers'

// The user's report, 4 Nov: in a chat 470-560px wide a finished sub-agent's folded report and KOLONİ's "What it did" line
// under it ran past the chat's right edge, and the message list scrolled sideways. One real turn gives a real record; the
// page is then handed it with two sub-agents' reports in it, as a CLI Lead's chat has them (no model plays such a turn).

type Json = Record<string, unknown>
const TASK =
  'Project: ./ is the project folder (the notes app; standard library only). Make the docs match the server and add a test.'
const REPORTS = [
  [
    'dbg',
    'Debugger',
    'The docs now match the server, and python -m unittest discover -s tests passes with the new routes in it as well.',
    'read 1 file, wrote 2 ("docs/api.md", "test_server_routes_with_a_rather_long_name.py"), ran 1 command, last the one that ran the whole suite',
  ],
  [
    'tst',
    'Tester',
    'The full suite passes, the new test passes on its own, and nothing else in the notes app had to change for it.',
    'read 0 files, wrote 0, ran 1 command, last tests/test_server_routes_with_a_rather_long_name.py run on its own',
  ],
]

/** At the chat's width now: how far its list scrolls sideways, which of `rows` run past the list's end, and what in the chat scrolls sideways. */
const overflowOf = (chat: Locator, rows: string) =>
  chat.evaluate((root, rows) => {
    const list = root.querySelector('.msg-list')
    if (!list) throw new Error('no message list')
    const end = list.getBoundingClientRect().left + list.clientWidth
    return {
      wide: list.scrollWidth - list.clientWidth,
      past: [...list.querySelectorAll(rows)]
        .filter(row => row.getBoundingClientRect().right > end + 1)
        .map(row => `${row.getAttribute('class')}: ${row.textContent?.slice(0, 40)}`),
      sideways: [root, ...root.querySelectorAll('*')]
        .filter(
          el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1,
        )
        .map(el => el.getAttribute('class')),
    }
  }, rows)

for (const theme of ['light', 'dark'] as const)
  test(`a finished sub-agent's report and what it did stay inside the chat: nothing scrolls sideways (${theme})`, async ({
    page,
  }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page)
    await say(page, 'hello, two sub-agents', 'Hello! Ask me to read or change a file.')
    const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & {
      agents: Json[]
      messages: Json[]
    }
    const lead = snap.agents[0]
    const answer = snap.messages.find(m => m.role === 'assistant')!
    const record = {
      ...snap,
      agents: [
        lead,
        ...REPORTS.map(([aid, name]) => ({
          ...lead,
          id: aid,
          name,
          role_name: name,
          parent_agent_id: lead.id,
          depth: 1,
          status: 'completed',
          task: TASK,
          tool_call_id: `s-${aid}`,
        })),
      ],
      tool_calls: [
        ...((snap.tool_calls as Json[]) ?? []),
        ...REPORTS.map(([aid, name], seq) => ({
          id: `s-${aid}`,
          run_id: answer.run_id,
          agent_id: lead.id,
          message_id: answer.id,
          origin: 'koloni',
          parent_call_id: null,
          outside_folder: null,
          why_asked: null,
          seq: 100 + seq,
          provider_call_id: `s-${aid}`,
          name: 'spawn_agent',
          arguments: JSON.stringify({ role: name, task: TASK }),
          status: 'succeeded',
          result: `${name} finished.`,
          started_at: answer.created_at,
          ended_at: answer.created_at,
        })),
      ],
      messages: [
        ...snap.messages,
        ...REPORTS.map(([aid, name, said, did]) => ({
          ...answer,
          id: `m-${aid}`,
          role: 'agent',
          agent_id: lead.id,
          from_agent_id: aid,
          content: `${name} finished.\n\n${said}\n\nMore of the report.\n\nWhat it did, from KOLONİ's record: ${did}.`,
        })),
      ],
    }
    await page.route(`**/api/conversations/${id}`, route =>
      route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback(),
    )
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
      const { wide, past, sideways } = await overflowOf(chat, '.msg-from, .msg-from > *, .tool-run-what, .tool-row')
      expect(wide, `the list at ${width}px scrolls sideways by`).toBeLessThanOrEqual(1)
      expect(past, `rows past the list's end at ${width}px`).toEqual([])
      expect(sideways).toEqual([])
      // KOLONİ's record wraps, all of it in sight; the folded line cuts with an ellipsis.
      const did = chat.getByText(/^What it did, from KOLONİ's record: read 1 file/)
      await expect(did).toContainText('last the one that ran the whole suite.')
      expect(
        await did.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().height > 30),
      ).toBe(true)
      await style.evaluate(el => el.remove())
    }
  })

// 0.1.4: in the narrowest column (340px) a turn's card leaves an approval card about 250px, and a button does not wrap
// (`.btn` is nowrap): "Always allow GET to <host>" ran past the chat's edge. So did a host of 40 characters in its
// tag (nowrap too) and a Windows path outside the project (no place to break at a dot or a backslash). The page is
// handed a Lead's call that waits for its GET, one that waits to read outside the project, and an answer with an
// unbroken path in it, as a real turn would have them.
const HOST = 'kept-notes.archive-mirror.eu-central-1.example.org'
const PATH = `/srv/${'kept_notes_of_the_server'.repeat(8)}.md`
const FOLDER = `D:\\Archive\\${'kept_notes_of_the_server_'.repeat(3)}old`

test('at its narrowest the chat has nothing that scrolls sideways, a long approval button and an unbroken path included', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const id = await openFreshConversation(page)
  await say(page, 'hello, a narrow chat', 'Hello! Ask me to read or change a file.')
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & {
    agents: Json[]
    messages: Json[]
  }
  const lead = snap.agents[0]
  const answer = snap.messages.find(m => m.role === 'assistant')!
  const url = `https://${HOST}/notes`
  const record = {
    ...snap,
    messages: snap.messages.map(m =>
      m.id === answer.id ? { ...m, content: `Saved it under ${PATH}, and its copy under \`${PATH}\`.` } : m,
    ),
    tool_calls: [
      ...((snap.tool_calls as Json[]) ?? []),
      {
        id: 'c-get',
        run_id: answer.run_id,
        agent_id: lead.id,
        message_id: answer.id,
        origin: 'koloni',
        parent_call_id: null,
        outside_folder: null,
        why_asked: null,
        seq: 100,
        provider_call_id: 'c-get',
        name: 'http_request',
        arguments: JSON.stringify({ method: 'GET', url }),
        status: 'running',
        result: null,
        started_at: answer.created_at,
        ended_at: null,
      },
      {
        id: 'c-read',
        run_id: answer.run_id,
        agent_id: lead.id,
        message_id: answer.id,
        origin: 'koloni',
        parent_call_id: null,
        outside_folder: FOLDER,
        why_asked: null,
        seq: 101,
        provider_call_id: 'c-read',
        name: 'read_file',
        arguments: JSON.stringify({ path: `${FOLDER}\\notes.md` }),
        status: 'pending',
        result: null,
        started_at: answer.created_at,
        ended_at: null,
      },
    ],
    web_requests: [
      {
        id: 'w-get',
        run_id: answer.run_id,
        agent_id: lead.id,
        tool_call_id: 'c-get',
        kind: 'http',
        method: 'GET',
        target: url,
        host: HOST,
        headers: [],
        body_chars: null,
        status: 'proposed',
        created_at: answer.created_at,
        decided_at: null,
      },
    ],
  }
  await page.route(`**/api/conversations/${id}`, route =>
    route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback(),
  )
  await page.reload()
  const chat = page.getByRole('region', { name: 'Chat' })
  const card = chat.getByRole('article')
  await expect(card.getByRole('button', { name: `Always allow GET to ${HOST}` })).toBeVisible()
  await expect(card.getByRole('button', { name: `Allow reading this folder: ${FOLDER}` })).toBeVisible()
  await expect(card.getByText(/^Saved it under \/srv\/kept_notes/)).toBeVisible()

  await page.addStyleTag({ content: '.stage { --chat-w: 340px !important; }' })
  await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(340)
  // (All of the card: what of it runs past the list's end is named.)
  const { wide, past, sideways } = await overflowOf(chat, '.turn, .turn *')
  expect(past, "what of the card runs past the list's end").toEqual([])
  expect(wide, 'the list scrolls sideways by').toBeLessThanOrEqual(1)
  expect(sideways).toEqual([])
  // The path wraps in its paragraph, all of it in sight.
  const said = card.getByText(/^Saved it under \/srv\/kept_notes/)
  expect(
    await said.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().height > 30),
  ).toBe(true)
})
