import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { openAgentFold, openFreshConversation, settled } from './helpers'

const B26 = path.join(os.tmpdir(), 'koloni-docs', 'b26-shots')

/** Whether any two of the nodes that stand on the canvas itself (not inside a box) lie on each other. */
async function overlapping(page: Page) {
  return page.locator('.react-flow__node').evaluateAll(all => {
    const outside = all.filter(n => !(n as HTMLElement).dataset.id?.match(/^(tools|owntools|command|file|subagent):/))
    const rects = outside.map(n => n.getBoundingClientRect())
    return rects.some((a, i) =>
      rects.some((b, j) => i < j && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom),
    )
  })
}

test('two agents at work leave notes, you leave one too, and the notebook is on its tab and on the canvas', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const notes = chat.locator('.channel-message')

  await page.getByLabel('Message').fill('use the notebook')
  await page.getByRole('button', { name: 'Send' }).click()

  // Both reviewers have noted and reported; the lead asks before it reports, so the turn is still at work.
  await expect(chat.getByText('Anything to add before I report?')).toBeVisible({ timeout: 15_000 })
  // What the lead was handed from the notebook is not chat.
  await expect(chat.getByText('hello.py is mine.')).toHaveCount(0)

  // The Notes tab has both notes, each with who wrote it and who has read it. The lead has
  // read both; whether one reviewer read the other's depends on which was faster.
  const tab = chat.getByRole('tab', { name: /^Notes/ })
  await expect(tab).toContainText('2')
  await tab.click()
  await expect(notes).toHaveCount(2)
  const hello = notes.filter({ hasText: 'hello.py is mine.' })
  const check = notes.filter({ hasText: 'check.py is mine.' })
  await expect(hello.locator('.channel-head')).toContainText(/^Reviewer\d\d/)
  await expect(check.locator('.channel-head')).toContainText(/^Reviewer 2\d\d/)
  await expect(hello).toContainText(/handed to [12] of 2/)
  await expect(check).toContainText(/handed to [12] of 2/)
  await expect(hello).not.toContainText('not yet to Lead')

  // You write one while the turn is at work. Nobody has taken a step since, so nobody has read it.
  await chat.getByLabel('A note for every agent working on this request').fill('Leave slow.py alone.')
  await chat.getByRole('button', { name: 'Post note' }).click()
  await expect(notes).toHaveCount(3)
  await expect(notes.nth(2).locator('.channel-head')).toContainText(/^You\d\d/)
  await expect(notes.nth(2)).toContainText('Leave slow.py alone.')
  await expect(notes.nth(2)).toContainText('handed to 0 of 3 · not yet to Lead, Reviewer, Reviewer 2')
  await expect(chat.getByLabel('A note for every agent working on this request')).toHaveValue('')

  // The lead goes on once it is answered, and is handed your note before its next step.
  // The reviewers finished before it was written: they never read it, and it says so.
  await chat.getByRole('tab', { name: 'Chat' }).click()
  await chat.getByRole('button', { name: 'no', exact: true }).click()
  await expect(chat.getByText('The notes are in.')).toBeVisible()
  await expect(chat.getByText('Leave slow.py alone.')).toHaveCount(0)
  await tab.click()
  await expect(notes.nth(2)).toContainText('handed to 1 of 3 · not yet to Reviewer, Reviewer 2')
  // The turn is over: its notebook can be read, not written on.
  await expect(chat.getByLabel('A note for every agent working on this request')).toBeDisabled()
  await expect(chat.getByText('This work is over: its notebook is closed.')).toBeVisible()

  // On the canvas the notes are on cards (K-shared-bagli; batch-26): each reviewer's on its own, level with its box and
  // joined to it by one line; yours on everyone's, beside the Lead. (KOLONİ's is on the Notes tab.) Clear of every box.
  await expect(page.locator('.react-flow__node-shared')).toHaveCount(3)
  const block = (who: string) => page.getByRole('region', { name: `${who}: shared, noted, remembered`, exact: true })
  await expect(block('Everyone')).toContainText('You: “Leave slow.py alone.”')
  await expect(block('Reviewer')).toContainText('Reviewer: “hello.py is mine.”')
  await expect(block('Reviewer 2')).toContainText('Reviewer 2: “check.py is mine.”')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(3)
  await expect.poll(() => overlapping(page)).toBe(false)
  // A line runs to the card of each reviewer and from the Lead to everyone's; with the request and the two hand-offs, six.
  await expect(page.locator('.react-flow__edge')).toHaveCount(6)
  await settled(page)
  mkdirSync(B26, { recursive: true })
  await page.screenshot({ path: path.join(B26, 'cards-no-teams-light.png') })

  // A note's row opens the Notes tab at that note.
  await block('Reviewer 2').getByRole('button', { name: /check\.py is mine\.” - open it on the Notes tab$/ }).click()
  await expect(chat.getByRole('tab', { name: /^Notes/ })).toHaveAttribute('aria-selected', 'true')
  await expect(chat.locator('.channel-message').filter({ hasText: 'check.py is mine.' })).toBeInViewport()

  // The lead's own window shows each note it was handed as a note from the notebook, with
  // who wrote it - not as a message sent to it. (The lead is selected first, so that the double
  // click lands twice on a node that has stopped moving.)
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  const lead = page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Orchestrator$/ }) }).locator('.node-title')
  await lead.click()
  await expect(inspector).toContainText('Lead')
  await lead.dblclick()
  const own = page.getByRole('region', { name: 'Agent window' })
  await openAgentFold(own, 'Every step as recorded')
  await expect(own.getByText('note from the notebook, written by you')).toBeVisible()
  await expect(own.getByText('note from the notebook, written by Reviewer 2')).toBeVisible()

  // A reload shows the same notebook from the records. (In the dark theme: its picture too.)
  await page.evaluate(() => localStorage.setItem('koloni-theme', 'dark'))
  await page.reload()
  await page.getByRole('region', { name: 'Chat' }).getByRole('tab', { name: /^Notes/ }).click()
  const again = page.getByRole('region', { name: 'Chat' }).locator('.channel-message')
  // (and KOLONİ's own, written as the turn ended)
  await expect(again).toHaveCount(4)
  await expect(again.nth(3).locator('.channel-head')).toContainText(/^KOLONİ/)
  await expect(again.nth(2)).toContainText('handed to 1 of 3 · not yet to Reviewer, Reviewer 2')
  await expect(block('Everyone')).toContainText('You: “Leave slow.py alone.”')
  await page.getByRole('region', { name: 'Chat' }).getByRole('tab', { name: 'Chat' }).click()
  await expect.poll(() => overlapping(page)).toBe(false)
  await settled(page)
  await page.screenshot({ path: path.join(B26, 'cards-no-teams-dark.png') })
})

test('with no turn at work there is nothing to write on, and a turn that used nothing has no card', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('tab', { name: /^Notes/ }).click()
  await expect(chat.getByText('Notes that agents and you leave for everyone working on a message show here.')).toBeVisible()
  await expect(chat.getByLabel('A note for every agent working on this request')).toBeDisabled()
  await expect(chat.getByText('Nothing is at work. A note can be written while something is.')).toBeVisible()

  await chat.getByRole('tab', { name: 'Chat' }).click()
  await page.getByLabel('Message').fill('hello')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(1)
  await expect(page.locator('.react-flow__node-shared')).toHaveCount(0)
})
