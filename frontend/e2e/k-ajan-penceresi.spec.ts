import type { Locator } from '@playwright/test'
import { expect, test } from './fixtures'
import { openAgentFold, openFreshConversation, OWN, rail, shot } from './helpers'

/** The lines of facts, as they read: each name, then its value. */
const rows = (root: Locator) => root.locator('.agent-sum > *').allTextContents()
/** A line's value by its name. */
const line = (top: string[], name: string) => top[top.indexOf(name) + 1]
/**
 * K-devir-1: "Handed on from" names the project's earlier agents whose work the agent was briefed with - those
 * that changed a file its task names (in any chat of the project), or for a new chat's lead the last ones that
 * ended. Whether there are any depends on what ran before in this project (every run starts empty): where the
 * row is, its text names each and its other chat (none is in this one; B-366) - or, until the server has said, or
 * of a chat since deleted, "an earlier agent".
 */
const ONE = String.raw`(?:.+ \(.+\) in chat «.*»|an earlier agent)`
const HANDED = new RegExp(`^${ONE}(, ${ONE}){0,2}$`)
const handed = (top: string[]) => {
  if (top.includes('Handed on from')) expect(line(top, 'Handed on from')).toMatch(HANDED)
}
/** The lines of facts, the handed names left out: those come as the server answers. */
const same = (top: string[]) => top.map((value, i) => (top[i - 1] === 'Handed on from' ? '' : value))
/** Each fold's own line, and whether it is open. */
const folds = (root: Locator) =>
  root.locator('details.agent-fold').evaluateAll(all => all.map(d => `${(d as HTMLDetailsElement).open ? 'open' : 'folded'}: ${d.querySelector('summary')?.textContent}`))

test('design A: the side panel is a short report card, the agent window the whole story with Details folded at its end', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()

  // The Reviewer, picked from its row in the chat: who asked what, its report, its changes, its numbers - no story.
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByText('Did', { exact: true })).toBeVisible()
  await expect(inspector.locator('.agent-asked')).toContainText('Asked by Orchestrator: Review hello.py')
  await expect(inspector.getByRole('region', { name: 'Report' })).toContainText('Looks fine.')
  expect(await folds(inspector)).toEqual(['open: Changes none'])
  await expect(inspector.locator('.agent-story')).toHaveCount(0)
  const inInspector = await rows(inspector)
  await shot(inspector, 'ab-inspector-light')
  await inspector.getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  await expect(own.getByText('Did', { exact: true })).toBeVisible()
  // The window takes the panel's room, and the focus.
  await expect(inspector).toHaveCount(0)
  await expect(own).toBeFocused()
  // R160: picked again while its window is open, the panel does not show it beside it.
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  await expect(inspector.getByText('Shown in its window.')).toBeVisible()
  await expect(inspector.getByText('Did', { exact: true })).toHaveCount(0)

  // The window: its report, its numbers as the panel has them (measured, none made up), its phases in words.
  const top = await rows(own)
  handed(top)
  expect(same(top)).toEqual(same(inInspector))
  expect(line(top, 'Did')).toMatch(/^0 files changed · 1 tool · 0 commands · 1 step$/)
  expect(line(top, 'Tokens')).toMatch(/^\d[\d,]* in \/ \d[\d,]* out$/)
  await expect(own.locator('h3')).toHaveText(['Report', 'What it did'])
  await expect(own.locator('.agent-report')).toContainText('Looks fine.')
  await expect(own.locator('.agent-story h4')).toHaveText(['Looked around', 'Wrote its report'])
  expect(await folds(own)).toEqual(['open: Changes none', 'folded: Sub-agents none', 'folded: Details model, usage, tools, raw steps'])
  await expect(page.getByRole('tab', { name: /^(Details|Messages|Sub-agents|Record|Raw stream|What it did|Changes|Summary)$/ })).toHaveCount(0)

  // Details and the raw steps in it, each step with its time, opened from the keyboard.
  await own.locator('details.agent-fold > summary', { hasText: 'Details' }).focus()
  await page.keyboard.press('Enter')
  // its model's window is not known here: its context is its tokens, and no fill is made up
  await expect(own.locator('dt', { hasText: 'Context' }).locator('xpath=following-sibling::dd[1]')).toHaveText(/^\d[\d,]* in \/ \d[\d,]* out$/)
  await expect(own.getByRole('meter', { name: 'Context used' })).toHaveCount(0)
  await own.locator('summary', { hasText: 'Every step as recorded' }).focus()
  await page.keyboard.press('Enter')
  await expect(own.getByText('read_file hello.py')).toBeVisible()
  await expect(own.locator('.agent-step-time').first()).toHaveText(/\d{1,2}:\d{2}:\d{2}/)
  // K-inspector: its steps a timeline (each tool, its result's size), its raw stream a Copy raw.
  await own.getByText(/^result [\d,]+ chars/).first().waitFor()
  await expect(own.getByRole('button', { name: 'Copy raw' })).toBeVisible()
  await shot(own, 'ab-agent-window-light')
  await page.getByRole('button', { name: 'Theme: switch to dark' }).click()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await shot(own, 'ab-agent-window-dark')
  await own.getByRole('button', { name: 'Close agent window' }).click()
  await expect(inspector.getByText('Did', { exact: true })).toBeVisible()
  await shot(inspector, 'ab-inspector-dark')
  await page.getByRole('button', { name: 'Theme: switch to light' }).click()
})

test('an agent whose older messages were summarised in its turn has that line once, in its window’s Details (B-98)', async ({ page, request }) => {
  const lead = async () => (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Lead')
  // A window the fake model's 800 tokens fill past three quarters: its older part is summarised in the turn.
  expect((await request.patch(`/api/roles/${(await lead()).id}`, { data: { context_window: 1000 }, headers: OWN })).ok()).toBe(true)
  try {
    await openFreshConversation(page)
    await page.getByLabel('Message').fill('Fill the context.')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('Summarised, and on.')).toBeVisible()

    await rail(page, 'Canvas').click()
    await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Orchestrator/ }) })
      .last().locator('.node-title').click()
    const inspector = page.getByRole('complementary', { name: 'Inspector' })
    await expect(inspector.getByText('Did', { exact: true })).toBeVisible()
    const inInspector = await rows(inspector)
    // (the working state is raw: in the window's Details, not on the card)
    await expect(inspector.getByText(/messages? summarised for its model/)).toHaveCount(0)
    await inspector.getByRole('button', { name: 'Open window' }).click()
    const own = page.getByRole('region', { name: 'Agent window' })

    // A lead's task and report are the chat's message and answer, not on its record: not shown here.
    await expect(own.getByText('Did', { exact: true })).toBeVisible()
    const top = await rows(own)
    handed(top)
    expect(same(top)).toEqual(same(inInspector))
    await openAgentFold(own, 'Details')
    await expect(own.locator('dt', { hasText: 'Context' }).locator('xpath=following-sibling::dd[1]')).toHaveText(/^12% · 120 in \/ \d+ out$/) // its last step: 120 of 1000
    await expect(own.getByRole('meter', { name: 'Context used' })).toBeVisible()

    // The summarised line is one, whatever came while the window was open; nothing folded into ×N.
    await expect(own.getByText(/messages? summarised for its model/)).toHaveCount(1)
    await expect(own.getByText(/×\d/)).toHaveCount(0)
    await expect((await openAgentFold(own, 'Every step as recorded')).getByText(/read_file/).first()).toBeVisible()
  } finally {
    // Put back, failed or not, so that later runs start from the defaults.
    expect((await request.post(`/api/roles/${(await lead()).id}/reset`, { headers: OWN })).ok()).toBe(true)
  }
})

test('B-157: at 1048 px, opened from its node while the inspector is open, the agent window opens wholly beside it', async ({ page }) => {
  await page.setViewportSize({ width: 1048, height: 760 })
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('The reviewer found no problems.')).toBeVisible()
  const reviewer = page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Reviewer/ }) }).last()
  await reviewer.locator('.node-title').click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector).toBeVisible()
  await reviewer.locator('.node-title').dblclick()
  const own = page.getByRole('region', { name: 'Agent window' })
  await expect(own.getByText('Did', { exact: true })).toBeVisible()
  // (Only the panel's Open window closes it: the node's double click leaves it open.)
  await expect(inspector).toBeVisible()
  const [win, side] = [(await own.boundingBox())!, (await inspector.boundingBox())!]
  expect(win.x).toBeGreaterThanOrEqual(0)
  expect(win.x + win.width).toBeLessThanOrEqual(side.x)
})

test('B-157: at 1048 px the agent window stands wholly beside the inspector, and stays open when the inspector closes', async ({ page }) => {
  await page.setViewportSize({ width: 1048, height: 760 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await inspector.getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  await expect(own.getByText('Did', { exact: true })).toBeVisible()
  // (Open window closed the inspector: picked again, it comes back beside the window.)
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  await expect(inspector).toBeVisible()

  // Nothing of it under the inspector, nor past the page's edge.
  const [win, side] = [(await own.boundingBox())!, (await inspector.boundingBox())!]
  expect(win.x).toBeGreaterThanOrEqual(0)
  expect(win.x + win.width).toBeLessThanOrEqual(side.x)
  // What is drawn at its right edge is the window itself, not the inspector over it.
  const atEdge = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest('[aria-label="Agent window"]') !== null, [win.x + win.width - 4, win.y + win.height / 2])
  expect(atEdge).toBe(true)
  await shot(page, 'b157-window-beside-inspector-light')
  await page.getByRole('button', { name: 'Theme: switch to dark' }).click()
  await shot(page, 'b157-window-beside-inspector-dark')
  await page.getByRole('button', { name: 'Theme: switch to light' }).click()

  // The inspector closes; the window stays, read on its own - by ×, and by Esc.
  await inspector.getByRole('button', { name: 'Close inspector' }).click()
  await expect(inspector).toHaveCount(0)
  await expect(own).toBeVisible()
  await chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  await expect(inspector).toBeVisible()
  // (Esc from the chat is the chat's own: from the inspector it closes the inspector.)
  await inspector.getByRole('button', { name: 'Open window' }).focus()
  await page.keyboard.press('Escape')
  await expect(inspector).toHaveCount(0)
  await expect(own).toBeVisible()
  await expect(own.getByText('Did', { exact: true })).toBeVisible()
})
