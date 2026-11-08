import { writeFileSync } from 'node:fs'
import { expect, test, type APIRequestContext, type Locator, type Page } from './fixtures'
import { chatSheet, contrasts, editRole, more, openFreshConversation, openTurns, OWN, rail, say, settled, shot } from './helpers'
import { FAKE_CLAUDE, FAKE_MCP, MCP_PLAN, MCP_RECORD, PYTHON } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// The screenshots of slice 31 are taken twice - from the code as it was ("before") and as it
// is - by this same walk: SHOT_STAGE says which, and is part of each file's name.
const STAGE = process.env.SHOT_STAGE || 'after'

/** A server with as many tools as a real one has (REA: 170): the stand-in's own eight, and these. */
const MANY = Array.from({ length: 162 }, (_, n) => {
  const [verb, thing] = [['list', 'read', 'find', 'write', 'check', 'export'][n % 6], ['listing', 'owner', 'valuation', 'contract', 'photo', 'viewing', 'offer', 'tenant', 'invoice'][n % 9]]
  return {
    name: `${verb}_${thing}_${n + 1}`,
    description: `${verb[0].toUpperCase()}${verb.slice(1)}s the ${thing} records of an office and returns them as JSON, newest first. Give a city to narrow it.`,
    inputSchema: { type: 'object', properties: { city: { type: 'string' }, limit: { type: 'integer' } }, required: ['city'] },
  }
})

interface Named {
  id: string
  name: string
}

/** What the walk needs to be there: two models with a tier, a role that asks for one, and a server with 170 tools. */
async function setUp(request: APIRequestContext) {
  const [local]: Named[] = await (await request.get('/api/providers')).json()
  const models = [
    { name: 'fake-quick', note: null, tier: 'fast' },
    { name: 'fake-strong', note: null, tier: 'strongest' },
  ]
  expect((await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models } })).ok()).toBe(true)
  const roles: Named[] = await (await request.get('/api/roles')).json()
  const reviewer = roles.find(role => role.name === 'Reviewer')!
  expect((await request.patch(`/api/roles/${reviewer.id}`, { headers: OWN, data: { tier: 'strongest' } })).ok()).toBe(true)
  writeFileSync(MCP_PLAN, JSON.stringify({ record: MCP_RECORD, more: MANY }))
  const made = await request.post('/api/mcp-servers', { headers: OWN, data: { name: 'many', command: [PYTHON, FAKE_MCP], env: { FAKE_MCP_PLAN: MCP_PLAN } } })
  expect(made.ok()).toBe(true)
  expect((await request.post(`/api/mcp-servers/${(await made.json()).id}/read`, { headers: OWN })).ok()).toBe(true)
}

/** Put back, so that whatever runs after starts from the defaults. */
async function putBack(request: APIRequestContext) {
  writeFileSync(MCP_PLAN, JSON.stringify({ record: MCP_RECORD }))
  for (const server of (await (await request.get('/api/mcp-servers')).json()) as Named[]) {
    if (server.name === 'many') await request.delete(`/api/mcp-servers/${server.id}`, { headers: OWN })
  }
  const roles: Named[] = await (await request.get('/api/roles')).json()
  await request.post(`/api/roles/${roles.find(role => role.name === 'Reviewer')!.id}/reset`, { headers: OWN })
  const [local, ...others]: Named[] = await (await request.get('/api/providers')).json()
  await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models: [] } })
  for (const other of others) if (other.name.startsWith('Contrast ')) await request.delete(`/api/providers/${other.id}`, { headers: OWN })
}

/**
 * The screens the eight items of slice 31 are about, one after the other, each photographed:
 * `31-<item>-<what>-<before|after>-<light|dark>.png` under runtime/shots. The photographs are taken
 * on request (KOLONI_SHOTS=1); an ordinary run walks the same screens and checks what they hold.
 */
async function walk(page: Page, theme: 'light' | 'dark') {
  const snap = async (name: string) => {
    if (process.env.KOLONI_SHOTS) await shot(page, `31-${name}-${STAGE}-${theme}`)
  }
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
  await openFreshConversation(page)
  expect(await page.locator('html').evaluate(root => root.classList.contains('dark'))).toBe(theme === 'dark')

  // 1 and 2: the row under the message box, and the three panels that open from it.
  await chat.getByRole('button', { name: /^Model: / }).click()
  await page.getByLabel('Provider').selectOption({ label: 'Local' })
  await page.getByLabel('Model name').fill('fake-strong')
  await page.getByLabel(/Orchestrator model: automatic/).check()
  await snap('2-picker')
  await chat.getByRole('button', { name: 'Use this model' }).click()
  await expect(chat.getByRole('button', { name: /^Model: Orchestrator: automatic · Local · fake-strong/ })).toBeVisible()
  await snap('1-composer')
  await more(page)
  await snap('2-more')
  await page.keyboard.press('Escape')
  // (The sub-agents' settings and the rules are the project's, in Settings - tek-ev: ⚙ Chat has a link there.)
  await expect((await chatSheet(page)).getByRole('button', { name: '0 run without asking →' })).toBeVisible()
  await page.keyboard.press('Escape')

  // 4: a turn of two nodes; the lead's three lines (what was guessed is in the side panel - the user's, 5 Nov).
  await say(page, 'hello, everything at once', 'Hello! Ask me to read or change a file.')
  await expect(page.locator('.react-flow__node-agent').first()).toContainText('Done ✓')
  await settled(page)
  await snap('4-canvas')

  // 3: the notes under the settings - the project's here; a provider's, a role's and a server's below.
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('form', { name: 'Project settings' })).toBeVisible()
  await snap('3-project-settings')
  await page.getByRole('button', { name: 'Close settings' }).click()

  // 7: how a state reads in the chat, in the turn list, on the canvas - and on the Board.
  await say(page, 'review the greeting', 'The reviewer found no problems.')
  await settled(page)
  await snap('7-status-canvas')
  await page.getByLabel('Message').fill('edit the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect((await openTurns(page)).locator('.turn-row').getByText('waits for you')).toBeVisible({ timeout: 20_000 })
  await rail(page, 'Board').click()
  await expect(page.getByRole('listitem').filter({ hasText: 'waits for you' }).first()).toBeVisible()
  await snap('7-status-board')
  await rail(page, 'Canvas').click()
  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })

  // 3 again: the note under a provider's list of models.
  await rail(page, 'Models').click()
  await page.getByRole('button', { name: /^Local/ }).click()
  await page.getByRole('tab', { name: 'Connection' }).click()
  await page.getByLabel('Never run a model that is not on this list').scrollIntoViewIfNeeded()
  await snap('3-models')
  await page.keyboard.press('Escape')

  // 5: the roles list (and 3 again: a role's limits).
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await expect(page.getByRole('button', { name: /^Debugger/ })).toBeVisible()
  await snap('5-roles')
  await editRole(page, 'Lead', 'tiers')
  await page.getByText('Safety stops for one agent', { exact: true }).click() // (a closed fold, at the end)
  await page.getByLabel('At most this many tokens').scrollIntoViewIfNeeded()
  await snap('3-agents')

  // 6: the Tools page with a server of 170 tools (and 3 again: the notes of its form).
  await rail(page, 'Tools').click()
  // (the only server: open under its row already)
  await expect(page.getByRole('button', { name: /^many/ })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('table', { name: 'Tools of many' })).toBeVisible()
  await snap('3-tools')
  await page.getByRole('table', { name: 'Tools of many' }).scrollIntoViewIfNeeded()
  await snap('6-tools')

  // 8: two pages of words in every size the app has.
  await rail(page, 'Usage').click()
  await expect(page.getByRole('heading', { name: 'Usage' })).toBeVisible()
  await expect(page.getByRole('table').first()).toBeVisible()
  await snap('8-type-usage')
  await rail(page, 'Memory').click()
  await expect(page.getByRole('tabpanel', { name: /^Facts/ })).toBeVisible()
  await snap('8-type-memory')
}

for (const theme of ['light', 'dark'] as const) {
  test(`shots: the screens of slice 31, ${theme}`, async ({ page, request }) => {
    test.setTimeout(180_000)
    await putBack(request)
    await setUp(request)
    try {
      await walk(page, theme)
    } finally {
      await putBack(request)
    }
  })
}

// --- what the screenshots show, held to ---------------------------------------------------------

/** The conversation's model given a long name: a provider, a model, and the lead's following the message. */
async function longModelName(page: Page) {
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: /^Model: / }).click()
  await page.getByLabel('Provider').selectOption({ label: 'Local' })
  await page.getByLabel('Model name').fill('fake-strong')
  await page.getByLabel(/Orchestrator model: automatic/).check()
  await chat.getByRole('button', { name: 'Use this model' }).click()
  // (Saved, its panel is gone: until then the box in it is one more thing with "message" in its name.)
  await expect(page.getByLabel('Provider')).toHaveCount(0)
  return chat.getByRole('button', { name: 'Model: Orchestrator: automatic · Local · fake-strong', exact: true })
}

/** Whether a page (or the document under it) scrolls sideways. */
const sideways = (page: Element) => page.scrollWidth > page.clientWidth || document.documentElement.scrollWidth > window.innerWidth

/** Whether what is drawn lies wholly inside the window. */
async function inWindow(page: Page, drawn: Locator) {
  const [box, view] = [await drawn.boundingBox(), page.viewportSize()]
  return box !== null && view !== null && box.x >= 0 && box.y >= 0 && box.x + box.width <= view.width && box.y + box.height <= view.height
}

/** Whether its words are all shown: none cut off at its end. */
const readInFull = (line: Locator) => line.evaluate(element => element.scrollWidth <= element.clientWidth)

/** How a state's label is drawn: its face, its size, and the dot before the word. */
const look = (label: Locator) =>
  label.evaluate(element => {
    const [word, dot] = [getComputedStyle(element), getComputedStyle(element, '::before')]
    return [word.fontFamily, word.fontSize, dot.width, dot.height, dot.borderRadius, dot.backgroundColor === word.color]
  })

test('the row under the message box reads whole, ⚙ Chat and the model open their panels the same way: inside the window, closed by Esc, a click anywhere else or their own button', async ({ page, request }) => {
  test.setTimeout(120_000)
  await putBack(request)
  await setUp(request)
  try {
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    const model = await longModelName(page)
    const sheet = chat.getByRole('button', { name: 'This chat’s settings' })
    const moreButton = chat.getByRole('button', { name: 'More', exact: true })

    // The model's button, on a line of the row with New topic and Workspace, says the model first: where the chat is
    // narrow its end is cut with "…" (the user's pick, 7 Nov), and its tooltip says all of it.
    await expect(model.locator('.model-picker-label')).toHaveText('fake-strong · Local · Orchestrator: automatic')
    await expect(model).toHaveAttribute('title', /^Orchestrator: automatic · Local · fake-strong: /)
    // The buttons that were an icon alone say what they open, and are named as they were.
    await expect(sheet).toHaveText('Chat')
    // Every control is one height; the model stands over how far the conversation may go, More and Send,
    // which share a line.
    const [m, r, level, opener, send] = await Promise.all(
      [model, sheet, chat.getByLabel('Permission level'), moreButton, chat.getByRole('button', { name: 'Send' })].map(
        async control => (await control.boundingBox())!,
      ),
    )
    expect([m, r, level, opener, send].map(box => Math.round(box.height))).toEqual([30, 30, 30, 30, 30])
    expect(m.y + m.height).toBeLessThanOrEqual(level.y)
    expect([opener.y, send.y]).toEqual([level.y, level.y])

    // (The model's last: More, open from above, lies over its button.)
    const panels: [button: Locator, panel: Locator][] = [
      [sheet, chat.getByRole('dialog', { name: 'This chat' })],
      [model, chat.getByRole('form', { name: 'Model for this conversation' })],
    ]
    // In a big window and in a small one: each opens over the row, inside the window, with the focus in it.
    for (const size of [{ width: 1440, height: 900 }, { width: 1000, height: 560 }]) {
      await page.setViewportSize(size)
      for (const [button, panel] of panels) {
        const open = () => button.click()
        await open()
        await expect(panel).toBeFocused()
        expect(await inWindow(page, panel)).toBe(true)
        const [over, row] = [(await panel.boundingBox())!, (await button.boundingBox())!]
        expect(over.y + over.height).toBeLessThanOrEqual(row.y)
        expect(over.x).toBe((await chat.locator('.composer-row').boundingBox())!.x)
        // Esc closes it, and the focus is back on the button that opened it.
        await page.keyboard.press('Escape')
        await expect(panel).toHaveCount(0)
        await expect(button).toBeFocused()
        // A click anywhere else closes it (here: at the window's edge, which no panel reaches).
        await open()
        await expect(panel).toBeVisible()
        await page.mouse.click(size.width - 4, 200)
        await expect(panel).toHaveCount(0)
        // And so does its own button.
        await open()
        await expect(panel).toBeVisible()
        await button.click()
        await expect(panel).toHaveCount(0)
      }
    }
  } finally {
    await putBack(request)
  }
})

test('a turn of two nodes opens closer and whole; an agent’s header and a role’s row say everything; a server of 170 tools is searched and set at once; a state is one label everywhere', async ({ page, request }) => {
  test.setTimeout(120_000)
  await putBack(request)
  await setUp(request)
  try {
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    const list = page.getByRole('complementary', { name: 'Recent' })
    const stage = page.locator('.canvas-flow')
    await longModelName(page)

    // 4. A request and its lead: drawn closer than life-size, a little, and all of both in the stage.
    await say(page, 'hello, everything at once', 'Hello! Ask me to read or change a file.')
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await settled(page)
    const zoom = await page.locator('.react-flow__viewport').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)
    expect(zoom).toBeGreaterThan(1)
    expect(zoom).toBeLessThanOrEqual(1.25)
    const around = (await stage.boundingBox())!
    for (const node of await page.locator('.react-flow__node').all()) {
      const box = (await node.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(around.x)
      expect(box.x + box.width).toBeLessThanOrEqual(around.x + around.width)
      expect(box.y).toBeGreaterThanOrEqual(around.y)
      expect(box.y + box.height).toBeLessThanOrEqual(around.y + around.height)
    }
    // The lead's first line: its name read in full, then provider · model (the user's, 5 Nov: three lines at most).
    const head = page.locator('.react-flow__node-agent .node-head').first()
    const [name, where] = [head.locator('.node-title'), head.locator('.node-where')]
    await expect(name).toHaveText('Orchestrator')
    await expect(where).toHaveText(' · Local · fake-strong')
    expect(await readInFull(name)).toBe(true)
    const [named, ran] = [(await name.boundingBox())!, (await where.boundingBox())!]
    expect(Math.round(ran.x)).toBe(Math.round(named.x + named.width))
    expect(await page.locator('.react-flow__node-agent .node').first().evaluate(element => (element as HTMLElement).offsetHeight)).toBe(80)

    // 7. A state is said by one label - a dot and its word, in one face and size - in the chat, the turn list,
    // on the canvas and on the Board.
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    const inChat = chat.getByRole('button', { name: /^Reviewer Review hello\.py/ }).locator('.status')
    await openTurns(page)
    const inList = list.locator('.turn-row').first().locator('.status')
    const onNode = page.locator('.react-flow__node-agent .status')
    await expect(inChat).toHaveText('done')
    await expect(inList).toHaveText('done')
    await expect(onNode).toHaveText(['Done ✓', 'Done ✓'])
    const drawn = await look(inChat)
    expect(drawn.slice(2)).toEqual(['6px', '6px', '50%', true])
    for (const label of [inList, onNode.first()]) expect(await look(label)).toEqual(drawn)
    expect(new Set(await Promise.all([inChat, inList, onNode.first()].map(label => label.evaluate(element => getComputedStyle(element).color)))).size).toBe(1)
    await page.getByLabel('Message').fill('edit the greeting')
    await page.getByRole('button', { name: 'Send' }).click()
    await openTurns(page)
    await expect(list.locator('.turn-row').getByText('waits for you')).toBeVisible({ timeout: 20_000 })
    await rail(page, 'Board').click()
    const onBoard = page.locator('.board-agent .status').filter({ hasText: 'waits for you' }).first()
    await expect(onBoard).toBeVisible()
    expect(await look(onBoard)).toEqual(drawn)
    await rail(page, 'Canvas').click()
    await chat.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })

    // 5. A role's row in the library (slice 63b): its name, then how many teams it is in beside it - none of it cut; its
    // tier rule on its panel (slice 81b).
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    const library = page.getByRole('complementary', { name: 'Roles' })
    await library.getByRole('button', { name: /^Reviewer/ }).click()
    await expect(page.getByRole('complementary', { name: 'Role Reviewer' })).toContainText('Which modelAlways strongest')
    const rows = await library.locator('.lib-row-open').evaluateAll(all =>
      all.map(row => {
        const [name, uses] = ['.lib-row-name', '.lib-uses'].map(line => row.querySelector(line)!)
        const whole = (line: Element) => line.scrollWidth <= line.clientWidth && line.scrollHeight <= line.clientHeight
        return { beside: uses.getBoundingClientRect().left >= name.getBoundingClientRect().right - 1, whole: [name, uses].every(whole) }
      }),
    )
    expect(rows.length).toBeGreaterThanOrEqual(11)
    expect(rows.filter(row => !row.beside || !row.whole)).toEqual([])

    // 6. A server of 170 tools: the table scrolls in a box of its own, with none of the tools' inputs open.
    await rail(page, 'Tools').click()
    // (the only server: open under its row already)
    await expect(page.getByRole('button', { name: /^many/ })).toHaveAttribute('aria-expanded', 'true')
    const table = page.getByRole('table', { name: 'Tools of many' })
    // the first 8, and the rest a click away (0.1.0-ui)
    await expect(table.getByRole('row')).toHaveCount(9)
    await page.getByRole('button', { name: '+ 162 more' }).click()
    await expect(table.getByRole('row')).toHaveCount(171)
    const box = (await page.locator('.tools-table').boundingBox())!
    expect(box.height).toBeGreaterThan(300)
    expect(box.height).toBeLessThanOrEqual(900 * 0.62 + 1)
    await expect(page.locator('.tools-table details[open]')).toHaveCount(0)
    // what is on and what it adds is said above the table too
    const above = page.getByText(/^170 of 170 tools on · about [\d,]+ characters added to every model step$/)
    await expect(above).toBeVisible()
    expect((await above.boundingBox())!.y).toBeLessThan(box.y)
    // the roles that may use it are in reach without reading 170 rows
    await expect(page.getByRole('group', { name: 'Roles that may use it' })).toBeVisible()
    // a search by name or by description, as it is typed
    const find = page.getByRole('searchbox', { name: 'Find a tool' })
    await find.pressSequentially('contract')
    await expect(table.getByRole('row')).toHaveCount(19)
    await expect(page.getByText(/· 18 shown$/)).toBeVisible()
    await find.fill('Says back what')
    await expect(table.getByRole('rowheader')).toHaveText(['echo'])
    await find.fill('no such tool')
    await expect(table).toHaveCount(0)
    await expect(page.getByText('No tool has “no such tool” in its name or description.')).toBeVisible()
    await find.fill('')
    await expect(table.getByRole('row')).toHaveCount(171)
    // every tool set to Off, then to Ask: one request each, with all 170 in it
    const sent: string[] = []
    page.on('request', asked => {
      if (asked.method() === 'PATCH' && /\/api\/mcp-servers\//.test(asked.url())) sent.push(asked.postData() ?? '')
    })
    await page.getByRole('button', { name: 'Set all to Off' }).click()
    await expect(page.getByText(/^0 of 170 tools on · about 0 characters added to every model step$/)).toBeVisible()
    await expect(page.getByLabel('When an agent calls echo')).toHaveValue('off')
    expect(sent).toHaveLength(1)
    expect(Object.values(JSON.parse(sent[0]).marks)).toEqual(Array(170).fill('off'))
    await page.getByRole('button', { name: 'Set all to Ask' }).click()
    await expect(above).toBeVisible()
    await expect(page.getByLabel('When an agent calls echo')).toHaveValue('ask')
    expect(sent).toHaveLength(2)
    // (nothing gives all of them leave to run without asking)
    await expect(page.getByRole('button', { name: /^Set all to / })).toHaveText(['Set all to Ask', 'Set all to Off'])
  } finally {
    await putBack(request)
  }
})

for (const theme of ['light', 'dark'] as const) test(`in the ${theme} theme every text of the screens slice 31 changed stands out from what it is on (contrast 4.5 or more)`, async ({ page, request }) => {
  test.setTimeout(120_000)
  await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
  await putBack(request)
  await setUp(request)
  /** Every piece of text in it - what is folded or behind ⓘ opened first - against what it stands on. */
  const check = async (root: Locator, least: number) => {
    await root.locator('details.more, details.usage-fold').evaluateAll(folds => folds.forEach(fold => ((fold as HTMLDetailsElement).open = true)))
    await root.locator('.hint-bubble').evaluateAll(hints => hints.forEach(hint => ((hint as HTMLElement).hidden = false)))
    const pieces = await root.evaluate(contrasts)
    // (Hidden again: a hint shown by force lies over the buttons the test clicks next.)
    await root.locator('.hint-bubble').evaluateAll(hints => hints.forEach(hint => ((hint as HTMLElement).hidden = true)))
    expect(pieces.length).toBeGreaterThanOrEqual(least)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    return pieces
  }
  try {
    await openFreshConversation(page)
    expect(await page.locator('html').evaluate(root => root.classList.contains('dark'))).toBe(theme === 'dark')
    const chat = page.getByRole('region', { name: 'Chat' })
    const model = await longModelName(page)
    await expect(page.locator('html')).not.toHaveClass(/theme-switching/)

    // The row under the message box with More open, and each of its panels; the chat's top row.
    await more(page)
    await check(page.locator('.composer'), 6)
    await check(chat.locator('.chat-top'), 3)
    // (More closed: open, it lies over the model's line, where ⚙ Chat is.)
    await page.keyboard.press('Escape')
    for (const [button, panel, least] of [
      [chat.getByRole('button', { name: 'This chat’s settings' }), chat.getByRole('dialog', { name: 'This chat' }), 8],
      // (last: More, open from above, lies over its button)
      [model, chat.getByRole('form', { name: 'Model for this conversation' }), 8],
    ] as const) {
      await button.click()
      await expect(panel).toBeVisible()
      await check(panel, least)
      await button.click()
      await expect(panel).toHaveCount(0)
    }

    // The canvas: an agent's header; the turn list; the chat's rows; the Board.
    await say(page, 'hello, everything at once', 'Hello! Ask me to read or change a file.')
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    const heads = await check(page.locator('.react-flow__node-agent .node-head').first(), 2)
    // (they are the theme's colours: the name in its text colour, where it runs in the muted one)
    expect(heads.find(piece => /node-title/.test(piece.cls))).toMatchObject({ color: theme === 'dark' ? '228,230,234' : '42,34,24' })
    expect(heads.find(piece => /node-where/.test(piece.cls))).toMatchObject({ color: theme === 'dark' ? '176,182,194' : '110,96,74' })
    await check(await openTurns(page), 8)
    await page.keyboard.press('Escape')
    await check(chat.locator('.msg-list'), 5)
    await page.getByLabel('Message').fill('edit the greeting')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect((await openTurns(page)).locator('.turn-row').getByText('waits for you')).toBeVisible({ timeout: 20_000 })
    // Closed, the chat is a small box (slice 38e): its line says in honey what waits for the user.
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await expect(chat.getByText('1 waits for you')).toBeVisible()
    await check(chat, 4)
    await chat.getByRole('button', { name: /^Chat/ }).click()
    await rail(page, 'Board').click()
    await expect(page.locator('.board-agent .status').filter({ hasText: 'waits for you' }).first()).toBeVisible()
    // Its one line to Ready for you says so too (tek-ev §2), and at 1024 px the page does not scroll sideways.
    await expect(page.locator('.ready-line')).toContainText(/^\d+ things? waits? for you/)
    await check(page.locator('.memory-page'), 8)
    await page.setViewportSize({ width: 1024, height: 900 })
    expect(await page.locator('.memory-page').evaluate(sideways)).toBe(false)
    await page.setViewportSize({ width: 1440, height: 900 })
    await rail(page, 'Canvas').click()
    await chat.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })
    // (Workspace opened by itself on the change that waited; closed now)
    const view = page.getByRole('region', { name: 'Workspace' })
    await view.getByRole('button', { name: 'Close workspace' }).click()
    // What an agent shows opens it by itself; beside the small box, Workspace, and the window's tabs (slices 38e, 42c).
    await page.getByLabel('Message').fill('show the chart')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
    await expect(view.getByRole('img', { name: 'chart39.png' })).toBeVisible({ timeout: 10_000 })
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await expect(page.locator('.chat-dock').getByRole('button', { name: /^Workspace/ })).toBeVisible()
    await check(page.locator('.chat-dock'), 2)
    await check(view.getByRole('tablist', { name: 'Open files' }), 1)
    await check(view.locator('.view-where'), 1)
    await view.getByRole('button', { name: 'Close workspace' }).click()
    await chat.getByRole('button', { name: /^Chat/ }).click()

    // The settings whose notes were folded: the project's, a provider's, a role's, a server's.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    // (A page of sections, one shown at a time: the list, then each section - together as much text as the one form held.)
    const settings = page.getByRole('form', { name: 'Project settings' })
    await check(settings.locator('.agents-list'), 11)
    let pieces = 0
    for (const section of ['Agents', 'Asking and away', 'New chats start with', 'Limits and money', 'Commands and secrets', 'Checks and git', 'Memory and web', 'Notifications']) {
      await settings.getByRole('button', { name: new RegExp(`^${section}`) }).click()
      pieces += (await check(settings.locator('.role-editor'), 1)).length
    }
    expect(pieces).toBeGreaterThanOrEqual(30)
    await page.getByRole('button', { name: 'Close settings' }).click()
    await rail(page, 'Models').click()
    await check(page.locator('.paged'), 10)
    await page.getByRole('button', { name: /^Local/ }).click()
    await check(page.locator('.provider-dialog'), 5)
    await page.getByRole('tab', { name: 'Connection' }).click()
    await expect(page.getByLabel('Never run a model that is not on this list')).toBeVisible()
    await check(page.locator('.provider-dialog'), 20)
    // Slice 40: each mark beside a model, and the card of a CLI that is not there. (Made now and
    // read on a fresh page, so the rest of the walk is as it was.)
    for (const [name, kind, executable] of [
      ['Contrast Codex', 'codex_cli', 'no-such-codex-for-the-contrast-test'],
      ['Contrast Claude', 'claude_cli', FAKE_CLAUDE],
    ])
      expect((await request.post('/api/providers', { headers: OWN, data: { name, kind, executable } })).ok()).toBe(true)
    await page.reload()
    await rail(page, 'Models').click()
    await page.getByRole('button', { name: /^Local/ }).click()
    await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
    await expect(page.getByRole('img', { name: 'Usable now' })).toBeVisible()
    await expect(page.getByRole('img', { name: 'Cannot be used: not offered by the provider now' })).toHaveCount(2)
    await check(page.locator('.provider-dialog'), 20)
    for (const [name, shown] of [
      ['Contrast Codex', page.getByRole('note', { name: 'How to install codex' })],
      ['Contrast Claude', page.getByRole('img', { name: /^Not known if usable/ }).first()],
    ] as const) {
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: new RegExp(`^${name}`) }).click()
      await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
      // (A CLI that is not there says how to install it on Connection.)
      if (name === 'Contrast Codex') await page.getByRole('tab', { name: 'Connection' }).click()
      await expect(shown).toBeVisible()
      await check(page.locator('.provider-dialog'), 20)
    }
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await expect(page.getByRole('button', { name: /^Debugger/ })).toBeVisible()
    // A role that ran, so its record table (slice 38c) is read too: on the page's History, its jobs listed (0.1.0-ui).
    await page.getByRole('tab', { name: 'History' }).click()
    await page.getByRole('combobox', { name: 'Role' }).selectOption('Reviewer')
    // Folded, closed (slice 38d): its line says the gist; opened, the table is there.
    const record = page.getByRole('table', { name: 'Record of the last 30 days' })
    await expect(record).toBeHidden()
    await page.locator('.role-record > summary').click()
    await expect(record).toBeVisible()
    await check(page.locator('.agents-page'), 60)
    // In a window 1024 px wide the table scrolls in a box of its own; the page never scrolls sideways.
    await page.setViewportSize({ width: 1024, height: 900 })
    expect(await page.locator('.agents-page').evaluate(sideways)).toBe(false)
    await page.setViewportSize({ width: 1440, height: 900 })
    await rail(page, 'Tools').click()
    // (the only server: open under its row already)
    await expect(page.getByRole('button', { name: /^many/ })).toHaveAttribute('aria-expanded', 'true')
    await page.getByRole('searchbox', { name: 'Find a tool' }).fill('contract')
    await expect(page.getByRole('table', { name: 'Tools of many' }).getByRole('row')).toHaveCount(19)
    await check(page.locator('.tools-page'), 60)
    // The Triggers page with none yet: its line, its ⓘ, and where it says there is none (slice 38c).
    await rail(page, 'Triggers').click()
    await expect(page.locator('.trigger-empty').getByRole('button', { name: 'New trigger' })).toBeVisible()
    // (Its how-it-works is behind the one ⓘ now, a piece of its own: fewer pieces than when it had two paragraphs.)
    await check(page.locator('.triggers-page'), 4)
    // The table pages and Memory (slice 38d): their line on top, what is folded, a table sorted; and none scrolls
    // sideways at 1024 px - Usage's tables scroll in a box of their own, a long conversation name is cut.
    const narrow = async (root: Locator) => {
      await page.setViewportSize({ width: 1024, height: 900 })
      expect(await root.evaluate(sideways)).toBe(false)
      await page.setViewportSize({ width: 1440, height: 900 })
    }
    await rail(page, 'Usage').click()
    const models = page.getByRole('table', { name: 'Usage by provider and model' })
    await models.getByRole('button', { name: 'Tokens sent' }).click()
    await expect(models.getByRole('columnheader', { name: 'Tokens sent' })).toHaveAttribute('aria-sort', 'descending')
    await expect(page.locator('.usage-stats').first()).toContainText('Tokens sent')
    await check(page.locator('.memory-page'), 40)
    await narrow(page.locator('.memory-page'))
    await page.getByRole('button', { name: 'Chats', exact: true }).click()
    await expect(page.getByLabel('Sort by')).toBeVisible()
    await check(page.locator('.conv-page'), 4)
    await narrow(page.locator('.conv-page'))
    await rail(page, 'Memory').click()
    await expect(page.getByRole('tabpanel', { name: /^Facts/ })).toBeVisible()
    await check(page.locator('.memory-page'), 15)
    await narrow(page.locator('.memory-page'))
  } finally {
    await putBack(request)
  }
})

/**
 * What the browser itself hands a screen reader - its own accessibility tree, not this test
 * runner's reckoning of one - for the boxes and fields whose name begins so.
 */
async function readOut(page: Page, name: RegExp) {
  const client = await page.context().newCDPSession(page)
  try {
    await client.send('Accessibility.enable')
    const { nodes } = await client.send('Accessibility.getFullAXTree')
    return nodes
      .filter(node => ['checkbox', 'textbox'].includes(String(node.role?.value)) && name.test(String(node.name?.value ?? '')))
      .map(node => ({ name: String(node.name?.value), description: String(node.description?.value ?? '') }))
  } finally {
    await client.detach()
  }
}

test('as the browser itself reads it out: a box named by a note with a hint keeps its whole name, and a field is described by all of its note, the part behind ⓘ too', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // A box whose note has a hint is named as it was before - by all of the note, and not by the hint's button.
  await chat.getByRole('button', { name: /^Model: / }).click()
  await expect(chat.getByRole('form', { name: 'Model for this conversation' })).toBeVisible()
  const [auto] = await readOut(page, /^Orchestrator model: automatic/)
  expect(auto.name).toMatch(/^Orchestrator model: automatic One more request for each message you send: .* asked how hard it is\. It overrides .* does not use it\. The Orchestrator then runs .* else the model above\.$/)
  expect(auto.name).not.toContain('About this')
  await page.keyboard.press('Escape')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await expect(settings).toBeVisible()
  await settings.getByRole('button', { name: /^Checks/ }).click()
  await expect(settings.getByLabel('Test before adding')).toBeVisible()
  const [commit] = await readOut(page, /^Save each sub-agent’s work as a git commit/)
  expect(commit.name).toMatch(/^Save each sub-agent’s work as a git commit One commit per piece of work\. Offered on the card .* top folder of a git repository\. Always your click: .* Nothing is pushed\.$/)
  expect(commit.name).not.toContain('About this')

  // A field is described by all of its note: what is behind ⓘ too, while it is closed. (A browser reads what a
  // description points at, shown or not.)
  const described = async () => (await readOut(page, /^At most this many agents at work in this project$/))[0].description
  await settings.getByRole('button', { name: /^Limits and money/ }).click()
  await expect(settings.getByLabel('At most this many agents at work in this project')).toBeVisible()
  await expect(settings.locator('.hint-bubble', { hasText: /waits for a slot/ })).toBeHidden()
  expect(await described()).toMatch(/^Counted over all of this project’s conversations together\. When that many are at work, .* The Board shows who is at work\.$/)
  expect(await described()).not.toContain('About this')
  // A note that warns of what a setting does not hold, or of what it runs, is not folded at all.
  await settings.getByRole('button', { name: /^Checks/ }).click()
  await expect(settings.getByLabel('Test before adding')).toBeVisible()
  expect((await readOut(page, /^Test before adding$/))[0].description).toMatch(/It runs by itself only where commands do: in Full auto/)
})
