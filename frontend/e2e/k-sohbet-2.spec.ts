import { expect, type Page, test } from './fixtures'
import { contrasts, level, openFreshConversation, say } from './helpers'

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
  await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
  await page.reload()
}

test('a finished turn folds its steps into one line that counts what failed; a sub-agent stays outside', async ({ page }) => {
  const { id, snap, lead, answer } = await realTurn(page)
  const at = String(answer.created_at)
  const call = (cid: string, message: string, seq: number, name: string, args: Json, status = 'succeeded') => ({
    id: cid, run_id: answer.run_id, agent_id: lead.id, message_id: message, origin: 'koloni', parent_call_id: null, outside_folder: null, why_asked: null,
    seq, provider_call_id: cid, name, arguments: JSON.stringify(args), status, result: 'ok', started_at: at, ended_at: at,
  })
  const step = (mid: string, content: string) => ({ ...answer, id: mid, content })
  const record = {
    ...snap,
    // (A fake turn is over in under a second: this one took 32s.)
    runs: snap.runs.map(r => ({ ...r, ended_at: new Date(Date.parse(String(r.started_at)) + 32_000).toISOString() })),
    agents: [lead, { ...lead, id: 'k2-coder', name: 'Coder', role_name: 'Coder', parent_agent_id: lead.id, depth: 1, status: 'completed', task: 'Fix the greeting', tool_call_id: 'k2-c3' }],
    messages: [snap.messages.find(m => m.role === 'user'), step('k2-m1', 'I’ll read it first.'), step('k2-m2', 'The Coder fixed it; I’ll check its edit.'), answer],
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

test('while a command runs the status line over the box and the Orchestrator’s box say what it does and for how long; Stop there ends the turn', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await level(page, 'full_auto')
  await page.getByLabel('Message').fill('run slow.py')
  await page.getByRole('button', { name: 'Send' }).click()
  const status = chat.locator('.composer-status')
  await expect(status).toContainText(/python -u slow\.py · \d+s/, { timeout: 15_000 })
  await expect(page.locator('.react-flow__node-agent .node-now')).toContainText(/python -u slow\.py · \d+s/)
  // Its clock ticks every second: no live region reads it out.
  expect(await status.evaluate(el => el.closest('[aria-live],[role=status],[role=alert]') === null && !el.querySelector('[aria-live],[role=status]'))).toBe(true)
  await status.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(status).toHaveText(/^Orchestrator is ready/)
})

test('1 and Enter answer the card over the box; the turn keeps one line, then Question / Answered', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('which greeting do you want to use?')
  await page.getByRole('button', { name: 'Send' }).click()
  const card = chat.getByRole('form', { name: 'Orchestrator asks' })
  await expect(card).toContainText(/^Orchestrator asks · /)
  // In its turn, one line: a click takes the focus to the card.
  const line = chat.getByRole('article').getByRole('button', { name: 'Orchestrator asks: Which greeting should I use? · waits for you' })
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
  await expect(page.getByLabel('Message')).toBeFocused()
  const asked = chat.locator('details.asked-row')
  await expect(asked.locator('summary')).toHaveText(/^Question: Which greeting should I use\?\s*Answered: hey$/)
  await asked.locator('summary').click()
  await expect(asked.getByRole('listitem', { name: 'hey, your answer' })).toBeVisible()
})

for (const theme of ['light', 'dark'] as const)
  test(`at 340, 420 and 760 px each row of the box is one line and nothing in the chat scrolls sideways; at 340 the model's name and Plan first give way, the level's name stays (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    for (const width of [340, 420, 760]) {
      const style = await page.addStyleTag({ content: `.stage { --chat-w: ${width}px !important; }` })
      await expect.poll(async () => Math.round((await chat.boundingBox())!.width)).toBe(width)
      const rows = await chat.evaluate(root => {
        const sideways = [root, ...root.querySelectorAll('*')].filter(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1)
        const end = root.getBoundingClientRect().right
        return {
          sideways: sideways.map(el => el.className),
          rows: ['.composer-status', '.composer-bar', '.composer-below'].map(at => {
            const row = root.querySelector(at)!
            const box = row.getBoundingClientRect()
            const kids = [...row.children].filter(c => (c as HTMLElement).offsetParent !== null && getComputedStyle(c).position !== 'absolute')
            return { at, height: Math.round(box.height), past: box.right > end + 1, lines: new Set(kids.map(c => Math.round(c.getBoundingClientRect().top / 12))).size }
          }),
        }
      })
      expect(rows.sideways, `what scrolls sideways at ${width}px`).toEqual([])
      for (const row of rows.rows) {
        expect(row.past, `${row.at} past the chat at ${width}px`).toBe(false)
        expect(row.height, `${row.at} one line at ${width}px`).toBeLessThanOrEqual(40)
      }
      const plan = chat.getByRole('button', { name: 'Plan first' })
      if (width === 340) {
        await expect(plan).toBeHidden()
        await expect(chat.locator('.composer-status .model-picker-label')).toBeHidden()
      }
      if (width === 760) await expect(plan).toBeVisible()
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

test('at 1024 px no window opens over the open chat: the Reviewer’s window and Workspace stand beside it', async ({ page }) => {
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
  await chat.locator('.composer-below').getByRole('button', { name: /^Workspace/ }).click()
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

test('at 1024 px a room’s window opens beside the open chat, never over it', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 700 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: 'More', exact: true }).click()
  await chat.getByRole('button', { name: /Work together/ }).click()
  const form = chat.getByRole('form', { name: 'Work together' })
  await form.getByLabel('Goal').fill('Look at the greeting together')
  await form.getByLabel('Posts by its members').fill('12')
  await form.getByRole('button', { name: 'Open the room' }).click()
  const room = page.getByRole('dialog', { name: 'Room: Look at the greeting together' })
  const waiting = room.getByRole('region', { name: 'Waits for you' })
  await expect(waiting.getByText('Shall the greeting stay hi?')).toBeVisible({ timeout: 20_000 })
  const [at, column] = [(await room.boundingBox())!, (await chat.boundingBox())!]
  expect(at.x).toBeGreaterThanOrEqual(column.x + column.width - 1)
  // (Its member answered, so that it ends.)
  await waiting.getByLabel('Your answer').fill('Yes')
  await waiting.getByRole('button', { name: 'Send answer' }).click()
  await expect(room.getByText('done · 1 of 1')).toBeVisible({ timeout: 20_000 })
})
