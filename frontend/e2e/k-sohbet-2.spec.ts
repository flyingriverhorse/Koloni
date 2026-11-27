import { expect, type Page, test } from './fixtures'
import { contrasts, level, openFreshConversation, say, shot } from './helpers'

// The chat, round 2 (0.1.5): VS Code's sizes, a turn without a frame, its steps folded at its end. No model plays a turn
// of many steps with a sub-agent: one real turn gives a real record, and the page is handed it with those steps in it.

type Json = Record<string, unknown>
type Snap = Json & { agents: Json[]; messages: Json[]; runs: Json[] }

/** A real turn's record, its lead and its answer. */
async function realTurn(page: Page) {
  const id = await openFreshConversation(page)
  await say(page, 'hello, a turn of steps', 'Hello! Ask me to read or change a file.')
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Snap
  return { id, snap, lead: snap.agents[0], answer: snap.messages.find(m => m.role === 'assistant')! }
}

/** The page shown `record` in place of the chat's own. */
async function shown(page: Page, id: string, record: Json) {
  await page.route(
    url => url.pathname === `/api/conversations/${id}`,
    route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()),
  )
  await page.reload()
}

test('a finished turn folds its steps into one line that counts what failed; a sub-agent stays outside', async ({
  page,
}) => {
  const { id, snap, lead, answer } = await realTurn(page)
  const at = String(answer.created_at)
  const call = (cid: string, message: string, seq: number, name: string, args: Json, status = 'succeeded') => ({
    id: cid,
    run_id: answer.run_id,
    agent_id: lead.id,
    message_id: message,
    origin: 'koloni',
    parent_call_id: null,
    outside_folder: null,
    why_asked: null,
    seq,
    provider_call_id: cid,
    name,
    arguments: JSON.stringify(args),
    status,
    result: 'ok',
    started_at: at,
    ended_at: at,
  })
  const step = (mid: string, content: string) => ({ ...answer, id: mid, content })
  const record = {
    ...snap,
    // (A fake turn is over in under a second: this one took 32s.)
    runs: snap.runs.map(r => ({ ...r, ended_at: new Date(Date.parse(String(r.started_at)) + 32_000).toISOString() })),
    agents: [
      lead,
      {
        ...lead,
        id: 'k2-coder',
        name: 'Coder',
        role_name: 'Coder',
        parent_agent_id: lead.id,
        depth: 1,
        status: 'completed',
        task: 'Fix the greeting',
        tool_call_id: 'k2-c3',
      },
    ],
    messages: [
      snap.messages.find(m => m.role === 'user'),
      step('k2-m1', 'I’ll read it first.'),
      step('k2-m2', 'The Coder fixed it; I’ll check its edit.'),
      answer,
    ],
    tool_calls: [
      call('k2-c1', 'k2-m1', 101, 'read_file', { path: 'a.py' }),
      call('k2-c2', 'k2-m1', 102, 'read_file', { path: 'gone.py' }, 'failed'),
      call('k2-c3', 'k2-m1', 103, 'spawn_agent', { role: 'Coder', task: 'Fix the greeting' }),
      call('k2-c4', 'k2-m2', 104, 'read_file', { path: 'a.py' }),
    ],
  }
  await shown(page, id, record)
  const chat = page.getByRole('region', { name: 'Chat' })
  const fold = chat.locator('details.turn-steps')
  await expect(fold.locator('summary')).toHaveText(/^Completed 4 steps in \d+s/)
  await expect(fold.locator('summary .tag-del')).toHaveText('1 failed')
  await expect(chat.getByText('I’ll read it first.')).toBeHidden()
  // The sub-agent's row stands outside, in sight; the answer under it.
  await expect(chat.getByRole('button', { name: /^Coder Fix the greeting/ })).toBeVisible()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  await fold.locator('summary').click()
  await expect(chat.getByText('I’ll read it first.')).toBeVisible()
})

test('while a command runs the status line over the box and the Orchestrator’s box say what it does and for how long; Stop there ends the turn', async ({
  page,
}) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await level(page, 'full_auto')
  await page.getByLabel('Message', { exact: true }).fill('run slow.py')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  const status = chat.locator('.composer-status')
  await expect(status).toContainText(/python -u slow\.py · \d+s/, { timeout: 15_000 })
  await expect(page.locator('.react-flow__node-agent .node-now')).toContainText(/python -u slow\.py · \d+s/)
  // Its clock ticks every second: no live region reads it out.
  expect(
    await status.evaluate(
      el =>
        el.closest('[aria-live],[role=status],[role=alert]') === null && !el.querySelector('[aria-live],[role=status]'),
    ),
  ).toBe(true)
  await status.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(status).toHaveText(/^Orchestrator is ready/)
})

/**
 * A line of work narrowed from 800 px, where all of it fits, down to 60, a step at a time (in one go: its clock does not tick
 * meanwhile): at each, which of its facts are in sight, whether each is whole or out of sight, how wide what it does is,
 * the line's height, and the model's name over the box (its width and the width it needs). `whole`: what it does with
 * room for all; `floor`: 12 characters of its font.
 */
function squeeze(line: Element) {
  const el = line as HTMLElement
  const what = el.querySelector<HTMLElement>('.composer-status-what, .node-live-what')!
  const facts = el.querySelector<HTMLElement>('.live-facts')!
  const pieces = [...facts.children] as HTMLElement[]
  const label = el.querySelector<HTMLElement>('.model-picker-label')
  const probe = what.appendChild(
    Object.assign(document.createElement('span'), { style: 'display:inline-block;width:12ch' }),
  )
  const floor = probe.getBoundingClientRect().width
  probe.remove()
  const state = () => {
    const box = facts.getBoundingClientRect()
    return {
      width: Math.round(el.getBoundingClientRect().width),
      what: what.getBoundingClientRect().width,
      height: Math.round(el.getBoundingClientRect().height),
      shown: pieces.filter(p => p.getBoundingClientRect().top < box.bottom - 0.5).map(p => p.textContent!.trim()),
      cut: pieces
        .filter(
          p => p.getBoundingClientRect().top < box.bottom - 0.5 && p.getBoundingClientRect().right > box.right + 0.5,
        )
        .map(p => p.textContent!.trim()),
      label: label && [label.getBoundingClientRect().width, label.scrollWidth],
    }
  }
  const natural = state()
  el.style.width = '2000px'
  const whole = what.getBoundingClientRect().width
  const all = pieces.map(p => p.textContent!.trim())
  const steps = []
  for (let width = 800; width >= 60; width -= 4) {
    el.style.width = `${width}px`
    steps.push(state())
  }
  el.style.width = ''
  return { natural, whole, floor, all, steps }
}

test('a line of work gives up its tier, then its tokens, then its time - each whole - before what it does is cut: on the canvas and over the box', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await level(page, 'full_auto')
  await page.getByLabel('Message', { exact: true }).fill('run slow.py')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  const status = chat.locator('.composer-status')
  const node = page.locator('.react-flow__node-agent .node-now')
  await expect(status).toContainText(/python -u slow\.py · \d+s/, { timeout: 15_000 })
  await expect(node).toContainText(/python -u slow\.py · \d+s/)
  for (const line of [status, node]) {
    const { natural, whole, floor, all, steps } = await line.evaluate(squeeze)
    const said = JSON.stringify({ natural, whole, floor, all, steps })
    // Time first, then what else is known: two at least here.
    expect(all.length, said).toBeGreaterThanOrEqual(2)
    expect(all[0], said).toMatch(/^· \d+s$/)
    // As it is, what it does is whole or 12 characters at least, and no fact is cut.
    expect(natural.what, said).toBeGreaterThanOrEqual(Math.min(whole, floor) - 0.5)
    expect(natural.cut, said).toEqual([])
    for (const at of steps) {
      // The facts go from the end, each whole; while any is in sight, what it does is whole; the line stays one line.
      const there = JSON.stringify({ at, whole, all })
      expect(at.shown, there).toEqual(all.slice(0, at.shown.length))
      expect(at.cut, there).toEqual([])
      if (at.shown.length > 0) expect(at.what, there).toBeGreaterThanOrEqual(whole - 0.05)
      expect(at.height, there).toBe(natural.height)
    }
    // Narrowed, every fact went, one after another, before what it does was cut.
    expect(steps[0].shown, said).toEqual(all)
    expect(new Set(steps.map(at => at.shown.length)).size, said).toBe(all.length + 1)
    expect(steps.at(-1)!.what, said).toBeLessThan(whole)
  }
  if (process.env.KOLONI_SHOTS) {
    await shot(page.locator('.react-flow__node-agent:has(.node-now)'), 'k-sohbet-2-live-node')
    for (const width of [420, 340]) {
      const style = await page.addStyleTag({ content: `.stage { --chat-w: ${width}px !important; }` })
      await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(width)
      await shot(status, `k-sohbet-2-live-status-${width}`)
      await style.evaluate(el => el.remove())
    }
  }
  await status.getByRole('button', { name: 'Stop' }).click()
  await expect(status).toHaveText(/^Orchestrator is ready/, { timeout: 15_000 })
})

test('over the box a long model name gives way after the facts and before what it does, down to its icon', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: /^Model: / }).click()
  await page.getByLabel('Provider').selectOption({ label: 'Local' })
  await page.getByLabel('Model name').fill('fake-strong-with-a-long-name')
  await page.getByLabel(/Orchestrator model: automatic/).check()
  await chat.getByRole('button', { name: 'Use this model' }).click()
  await level(page, 'full_auto')
  await page.getByLabel('Message', { exact: true }).fill('run slow.py')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  const status = chat.locator('.composer-status')
  await expect(status).toContainText(/python -u slow\.py · \d+s/, { timeout: 15_000 })
  for (const width of [420, 480]) {
    const style = await page.addStyleTag({ content: `.stage { --chat-w: ${width}px !important; }` })
    await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(width)
    const { natural, whole, floor, steps } = await status.evaluate(squeeze)
    const said = JSON.stringify({ width, natural, whole, floor })
    // As it is, what it does is whole or 12 characters at least; the model's name is what was cut.
    expect(natural.what, said).toBeGreaterThanOrEqual(Math.min(whole, floor) - 0.5)
    expect(natural.label![0], said).toBeGreaterThan(0)
    for (const at of steps) {
      const there = JSON.stringify({ width, at, whole })
      // The name is cut only once the facts are gone; what it does, only once the name is down to its icon.
      if (at.label![0] < at.label![1] - 1) expect(at.shown, there).toEqual([])
      if (at.what < whole - 0.05) expect(at.label![0], there).toBeLessThanOrEqual(1)
    }
    await style.evaluate(el => el.remove())
  }
  await status.getByRole('button', { name: 'Stop' }).click()
  await expect(status).toHaveText(/^Orchestrator is ready/, { timeout: 15_000 })
})

test('1 and Enter answer the card over the box; the turn keeps one line, then Question / Answered', async ({
  page,
}) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message', { exact: true }).fill('which greeting do you want to use?')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  const card = chat.getByRole('form', { name: 'Orchestrator asks' })
  await expect(card).toContainText(/^Orchestrator asks · /)
  // In its turn, one line: a click takes the focus to the card.
  const line = chat
    .getByRole('article')
    .getByRole('button', { name: 'Orchestrator asks: Which greeting should I use? · waits for you' })
  await line.click()
  await expect(card.getByRole('radio', { name: 'hello' })).toBeFocused()
  // Nothing of the card is past the chat's edge, over the message box.
  const [inCard, box] = [await card.boundingBox(), await chat.locator('.composer').boundingBox()]
  expect(inCard!.y + inCard!.height).toBeLessThanOrEqual(box!.y + 1)
  await page.keyboard.press('2')
  await expect(card.getByRole('radio', { name: 'hey' })).toBeChecked()
  await page.keyboard.press('Enter')
  await expect(chat.getByText('Going with hey.')).toBeVisible()
  await expect(card).toHaveCount(0)
  await expect(page.getByLabel('Message', { exact: true })).toBeFocused()
  const asked = chat.locator('details.asked-row')
  await expect(asked.locator('summary')).toHaveText(/^Question: Which greeting should I use\?\s*Answered: hey$/)
  await asked.locator('summary').click()
  await expect(asked.getByRole('listitem', { name: 'hey, your answer' })).toBeVisible()
})

for (const theme of ['light', 'dark'] as const)
  test(`at 340, 420 and 760 px each row of the box is one line and nothing in the chat scrolls sideways; at 340 the model's name gives way, the level's name stays (${theme})`, async ({
    page,
  }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    for (const width of [340, 420, 760]) {
      const style = await page.addStyleTag({ content: `.stage { --chat-w: ${width}px !important; }` })
      await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(width)
      const rows = await chat.evaluate(root => {
        const sideways = [root, ...root.querySelectorAll('*')].filter(
          el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1,
        )
        const end = root.getBoundingClientRect().right
        return {
          sideways: sideways.map(el => el.className),
          rows: ['.composer-status', '.composer-bar', '.composer-below'].map(at => {
            const row = root.querySelector(at)!
            const box = row.getBoundingClientRect()
            const kids = [...row.children].filter(
              c => (c as HTMLElement).offsetParent !== null && getComputedStyle(c).position !== 'absolute',
            )
            return {
              at,
              height: Math.round(box.height),
              past: box.right > end + 1,
              lines: new Set(kids.map(c => Math.round(c.getBoundingClientRect().top / 12))).size,
            }
          }),
        }
      })
      expect(rows.sideways, `what scrolls sideways at ${width}px`).toEqual([])
      for (const row of rows.rows) {
        expect(row.past, `${row.at} past the chat at ${width}px`).toBe(false)
        expect(row.height, `${row.at} one line at ${width}px`).toBeLessThanOrEqual(40)
      }
      if (width === 340) await expect(chat.locator('.composer-status .model-picker-label')).toBeHidden()
      await expect(chat.locator('.composer-level-name')).toBeVisible()
      await style.evaluate(el => el.remove())
    }
  })

for (const theme of ['light', 'dark'] as const)
  test(`the message box reads at 4.5 or more, in the ${theme} theme`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await level(page, 'auto_edit')
    expect((await page.locator('.composer').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })

test('at 1024 px no window opens over the open chat: the Reviewer’s window and Workspace stand beside it', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 700 })
  await openFreshConversation(page)
  await say(page, 'review the greeting', 'The reviewer found no problems.')
  const chat = page.getByRole('region', { name: 'Chat' })
  const edge = async () => {
    const at = (await chat.boundingBox())!
    return at.x + at.width
  }
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  const window = page.getByRole('region', { name: 'Agent window' })
  await expect(window).toBeVisible()
  expect((await window.boundingBox())!.x).toBeGreaterThanOrEqual((await edge()) - 1)
  await chat
    .locator('.composer-below')
    .getByRole('button', { name: /^Workspace/ })
    .click()
  const workspace = page.getByRole('region', { name: 'Workspace' })
  await expect(workspace).toBeVisible()
  expect((await workspace.boundingBox())!.x).toBeGreaterThanOrEqual((await edge()) - 1)
})

test('at 340 px what a turn did is one line, its details on it', async ({ page }) => {
  await openFreshConversation(page)
  await say(page, 'review the greeting', 'The reviewer found no problems.')
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.addStyleTag({ content: '.stage { --chat-w: 340px !important; }' })
  await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(340)
  const line = chat.locator('.turn-foot .turn-summary-line').last()
  const details = line.getByRole('button', { name: /^details/ })
  await expect(details).toBeVisible()
  const [words, button] = [(await line.locator('span').first().boundingBox())!, (await details.boundingBox())!]
  expect(Math.abs(words.y + words.height / 2 - (button.y + button.height / 2))).toBeLessThanOrEqual(2)
  expect((await line.boundingBox())!.height).toBeLessThan(26)
})

test('at 340 px a kept copy’s long folder wraps on its card: nothing in the chat scrolls sideways', async ({
  page,
}) => {
  const { id, snap, lead, answer } = await realTurn(page)
  const keptIn =
    'C:\\Users\\someone\\AppData\\Local\\koloni\\runtime\\copies\\conversation-3f2a9c1e\\agent-orchestrator-7b1d\\tree'
  const file = {
    path: 'hello.py',
    kind: 'changed',
    state: 'ready',
    diff: "--- a/hello.py\n+++ b/hello.py\n@@ -1 +1 @@\n-print('hi')\n+print('hey')",
    additions: 1,
    deletions: 1,
    note: null,
  }
  const at = String(answer.created_at)
  // A Coder the Orchestrator called, whose working copy was kept.
  const coder = {
    ...lead,
    id: 'k2-coder',
    name: 'Coder',
    role_name: 'Coder',
    parent_agent_id: lead.id,
    depth: 1,
    status: 'completed',
    task: 'Fix the greeting',
    tool_call_id: 'k2-c1',
  }
  const spawn = {
    id: 'k2-c1',
    run_id: answer.run_id,
    agent_id: lead.id,
    message_id: 'k2-m1',
    origin: 'koloni',
    parent_call_id: null,
    outside_folder: null,
    why_asked: null,
    seq: 101,
    provider_call_id: 'k2-c1',
    name: 'spawn_agent',
    arguments: JSON.stringify({ role: 'Coder', task: 'Fix the greeting' }),
    status: 'succeeded',
    result: 'ok',
    started_at: at,
    ended_at: at,
  }
  const kept = {
    id: 'k2-kept',
    run_id: answer.run_id,
    agent_id: coder.id,
    status: 'kept',
    files: [file],
    kept_in: keptIn,
    check: null,
    commit: null,
    created_at: at,
    decided_at: null,
  }
  await shown(page, id, {
    ...snap,
    agents: [lead, coder],
    messages: [
      snap.messages.find(m => m.role === 'user'),
      { ...answer, id: 'k2-m1', content: 'I’ll ask the Coder.' },
      answer,
    ],
    tool_calls: [spawn],
    merges: [kept],
  })
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.addStyleTag({ content: '.stage { --chat-w: 340px !important; }' })
  await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(340)
  await expect(chat.getByText(keptIn)).toBeVisible()
  const sideways = await chat.evaluate(root =>
    [root, ...root.querySelectorAll('*')]
      .filter(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1)
      .map(el => el.className),
  )
  expect(sideways).toEqual([])
})

test('an older turn that ends with a card keeps its Copy and Read aloud under it: nothing lies over the card’s buttons', async ({
  page,
}) => {
  const { id, snap, answer } = await realTurn(page)
  const later = {
    ...answer,
    id: 'k15-m',
    run_id: 'k15-r',
    content: 'Done again.',
    created_at: new Date(Date.parse(String(answer.created_at)) + 60_000).toISOString(),
  }
  const user = snap.messages.find(m => m.role === 'user')!
  const record = {
    ...snap,
    runs: [...snap.runs, { ...snap.runs[0], id: 'k15-r', created_at: later.created_at }],
    agents: [...snap.agents, { ...snap.agents[0], id: 'k15-a', run_id: 'k15-r' }],
    messages: [
      ...snap.messages,
      { ...user, id: 'k15-u', run_id: 'k15-r', content: 'and again', created_at: later.created_at },
      { ...later, agent_id: 'k15-a' },
    ],
    notes_offers: [
      { id: 'k15-o', run_id: answer.run_id, lines: ['docs/api.md was changed'], status: 'waiting', answer: null },
    ],
  }
  await shown(page, id, record)
  const chat = page.getByRole('region', { name: 'Chat' })
  const older = chat.getByRole('article').first()
  const button = older.getByRole('button', { name: 'Not now' })
  await button.scrollIntoViewIfNeeded()
  await older.hover()
  await expect(button).toBeVisible()
  const at = (await button.boundingBox())!
  // (Its middle and near its right end - inside its round corners -, where the foot of the turn would lie.)
  for (const [x, y] of [
    [at.x + at.width - 6, at.y + at.height / 2],
    [at.x + at.width / 2, at.y + at.height / 2],
  ])
    expect(
      await page.evaluate(([px, py]) => document.elementFromPoint(px, py)?.closest('button')?.textContent, [x, y]),
    ).toBe('Not now')
})
