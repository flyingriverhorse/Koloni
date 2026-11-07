import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { openFreshConversation, openTurns, openAgentFold } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const FACT = 'The service listens on port 8123.'

const rail = (page: Page, name: 'Memory' | 'Canvas') =>
  page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name, exact: true })

/**
 * Open the window of the last agent on the canvas that is called so: selected first, then
 * from the inspector (which moves the canvas as it opens, so a double click may miss).
 */
async function openWindowOf(page: Page, name: RegExp) {
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: name }) })
    .last().locator('.node-title').click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  return page.getByRole('region', { name: 'Agent window' })
}

test('an agent notes a fact from a file, you approve it, later agents are given it - until the file changes', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  // K-shared-bagli: the part memory played is a row on the card of whoever used it.
  const memoryNodes = page.locator('.shared-row').filter({ has: page.locator('.shared-kind-memory') })

  // Turn 1: the lead reads settings.txt, notes what it says with that line as the source,
  // and puts the note forward for the core.
  await page.getByLabel('Message').fill('note the port')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Noted where the port is set. It waits for you.')).toBeVisible({ timeout: 15_000 })
  // Nobody was given anything, one note was written: the Lead's, on the card beside it - on hover, who wrote what.
  await expect(memoryNodes).toHaveCount(1)
  await expect(memoryNodes).toHaveText('memory1 written')
  await expect(memoryNodes).toHaveAttribute('title', `Lead: ${FACT} · settings.txt:2-2 · put forward`)

  // The Memory page has it on the line of what waits for your word, with its source and how that stands.
  await rail(page, 'Memory').click()
  const waiting = page.getByRole('region', { name: 'Waits for you' })
  const core = page.getByRole('tabpanel', { name: /^Facts/ })
  const proposal = waiting.getByRole('article')
  // It is in the journal too, like any note.
  await page.getByRole('tab', { name: /^Notes/ }).click()
  await expect(page.getByRole('tab', { name: /^Notes/ })).toHaveText('Notes 1')
  await expect(page.getByRole('tabpanel', { name: /^Notes/ }).getByRole('article')).toContainText('put forward for the core')
  await page.getByRole('tab', { name: /^Facts/ }).click()
  await page.getByRole('button', { name: '● 1 fact waits for your word' }).click()
  await expect(proposal).toHaveCount(1)
  await expect(proposal).toContainText(FACT)
  await expect(proposal).toContainText('noted by Lead')
  await expect(proposal).toContainText('settings.txt:2-2')
  await expect(proposal).toContainText('source unchanged since noted')
  await expect(proposal).toContainText('read by the agent in the turn it was noted')
  // You are shown the line itself, not only where it is; it was not written during a turn.
  await expect(proposal.getByRole('group', { name: 'settings.txt:2-2 as it reads now' })).toContainText(FACT)
  await expect(proposal).not.toContainText('while agents were at work')
  await expect(core.getByText(/Nothing is in the core yet/)).toBeVisible()

  // Approved, it is in the core; nothing waits any more.
  await proposal.getByRole('button', { name: 'Approve', exact: true }).click()
  const fact = core.getByRole('article')
  await expect(fact).toHaveCount(1)
  await expect(fact).toContainText(FACT)
  await expect(fact).toContainText('settings.txt:2-2')
  await expect(fact).toContainText('source unchanged since noted')
  // (its line stays while the page is open, saying so, with the focus on it)
  await expect(waiting.getByText('Nothing waits for you.')).toBeFocused()
  await expect(page.getByRole('button', { name: 'Nothing waits for your word' })).toBeVisible()
  await expect(core.getByText(`${FACT.length} / 4 000 characters`)).toBeVisible()

  // Turn 2: the lead opens a Reviewer. The request, and the task the lead writes, name the
  // fact's subject (the port), so both are given the fact when they start.
  await rail(page, 'Canvas').click()
  await page.getByLabel('Message').fill('review the port of hello.py')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toHaveCount(1, { timeout: 15_000 })
  // The canvas draws this turn only, with the part memory played in it; the first turn is a
  // row of the turn list beside it.
  const turns = page.getByRole('complementary', { name: 'Recent' }).locator('.turn-row')
  await openTurns(page)
  await expect(turns).toHaveCount(2)
  // (The fact went to the Lead - everyone's, at the top - and to the Reviewer.)
  await expect(memoryNodes).toHaveText(['memory1 fact given', 'memory1 fact given'])

  // The sub-agent's own window says what it was given, with its source.
  let own = await openWindowOf(page, /^Reviewer$/)
  // (at the head of its steps)
  await openAgentFold(own, 'Every step as recorded')
  const given = own.getByRole('group', { name: 'Given from memory' })
  await expect(given.getByRole('listitem')).toHaveCount(1)
  await expect(given).toContainText(FACT)
  await expect(given).toContainText('settings.txt:2-2')
  await own.getByRole('button', { name: 'Close agent window' }).click()
  // The side panel's card leaves that to its window (picked again: Open window closed it).
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Reviewer$/ }) }).last().locator('.node-title').click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByText('Did', { exact: true })).toBeVisible()
  await expect(inspector.getByRole('group', { name: 'Given from memory' })).toHaveCount(0)

  await inspector.getByRole('button', { name: 'Close inspector' }).click()
  // A memory row opens the Memory page.
  await memoryNodes.last().click()
  await expect(page.getByRole('heading', { name: 'Memory', exact: true })).toBeVisible()
  await rail(page, 'Canvas').click()
  // The first turn, picked in the list, is drawn in its place: the Lead wrote the note.
  await openTurns(page)
  await turns.last().click()
  await expect(memoryNodes).toHaveText('memory1 written')

  // The file changes on disk: the line the fact rests on now says something else.
  writeFileSync(path.join(PROJECT_DIR, 'settings.txt'), '# settings\nThe service listens on port 9000.\n')
  await rail(page, 'Memory').click()
  await expect(fact).toContainText('source changed since noted: check again')
  await expect(fact).not.toContainText('source unchanged')
  // Looked at again, it shows the line as it reads now, and no "these are the same lines" (it changed).
  await fact.getByRole('button', { name: 'Look again' }).click()
  await expect(fact.getByRole('group', { name: 'settings.txt:2-2 as it reads now' })).toContainText('port 9000')
  await expect(fact.getByRole('button', { name: 'These are the same lines' })).toHaveCount(0)

  // Turn 3, on the same subject: nobody is given it. The turn has no memory node, and its
  // Reviewer no such section.
  await rail(page, 'Canvas').click()
  await page.getByLabel('Message').fill('review the port of hello.py again')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toHaveCount(2, { timeout: 15_000 })
  // A turn of yours that starts is the one drawn, though the first turn was picked before:
  // its two agents, and no memory node. The two turns before it still have theirs.
  await openTurns(page)
  await expect(turns).toHaveCount(3)
  await expect(turns.first()).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  await expect(memoryNodes).toHaveCount(0)
  await openTurns(page)
  await turns.nth(1).click()
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  await expect(memoryNodes).toHaveText(['memory1 fact given', 'memory1 fact given'])
  await openTurns(page)
  await turns.last().click()
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(1)
  await expect(memoryNodes).toHaveText('memory1 written')
  await openTurns(page)
  await turns.first().click()
  await expect(memoryNodes).toHaveCount(0)
  own = await openWindowOf(page, /^Reviewer$/)
  await expect(own.locator('.agent-report').getByText('Looks fine.')).toBeVisible() // its report, on top
  await expect(own.getByRole('group', { name: 'Given from memory' })).toHaveCount(0)
  await expect(inspector.getByRole('group', { name: 'Given from memory' })).toHaveCount(0)
  await own.getByRole('button', { name: 'Close agent window' }).click()

  // Removed from its ⋯, the fact is not deleted: it is under History and can be taken back.
  // (It also leaves the core empty for the tests that run after this one in the same project.)
  await rail(page, 'Memory').click()
  await fact.getByRole('button', { name: /^More for/ }).click()
  await page.getByRole('menuitem', { name: 'Remove' }).click()
  await expect(core.getByText(/Nothing is in the core yet/)).toBeVisible()
  await page.getByRole('tab', { name: /^History/ }).click()
  const past = page.getByRole('region', { name: 'Removed / replaced' }).getByRole('article').filter({ hasText: 'removed by you' })
  await expect(past).toContainText(FACT)
  await expect(past.getByRole('button', { name: 'Take back' })).toBeVisible()
})
