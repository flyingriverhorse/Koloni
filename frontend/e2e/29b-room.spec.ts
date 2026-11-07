import { expect, test } from './fixtures'
import { more, openFreshConversation, shot } from './helpers'

test('you open a room: its members share the work out and do it, you speak in it, and the lead has the last word', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // "Work together…", beside the message box: a goal, two members, what it may spend.
  await more(page)
  await chat.getByRole('button', { name: /Work together/ }).click()
  const form = chat.getByRole('form', { name: 'Work together' })
  await expect(form.getByLabel('Role of member 1')).toHaveValue('Coder')
  await expect(form.getByLabel('Role of member 2')).toHaveValue('Reviewer')
  await expect(form.getByRole('button', { name: 'Open the room' })).toBeDisabled() // no goal yet
  await form.getByLabel('Goal').fill('Look at the greeting together')
  await form.getByLabel('Posts by its members').fill('12')
  await shot(page, '29b-work-together')
  await form.getByRole('button', { name: 'Open the room' }).click()
  // More, where it was opened from, folds: it would lie over the room's window.
  await expect(chat.getByRole('button', { name: 'More', exact: true })).toHaveAttribute('aria-expanded', 'false')

  // Its window comes up by itself, over the canvas (AC). The Coder put its part on the list and took it before the work started.
  const room = page.getByRole('dialog', { name: 'Room: Look at the greeting together' })
  await expect(room).toBeVisible()
  const items = room.getByRole('region', { name: 'Items' })
  await expect(items).toContainText('1. Look at the greeting')
  await expect(items.locator('summary')).toHaveText(/^taken\s*1\. Look at the greeting\s*Coder$/) // its state, title and holder, on one line
  await expect(items).toContainText('hello.py')

  // The Coder cannot go on without you: its "blocked" post is a question card, here in the room's window.
  const waiting = room.getByRole('region', { name: 'Waits for you' })
  await expect(waiting.getByText('Shall the greeting stay hi?')).toBeVisible()
  await expect(waiting).toContainText('Coder asks')
  await expect(room.getByRole('group', { name: 'Spent of its budget' })).toContainText('1 of 12 posts')
  // The Reviewer waited for a post, read that one, and its work is over: its report is under Reports, its state in the head.
  const head = room.getByRole('region', { name: 'The room', exact: true })
  await expect(head).toContainText('Reviewer · done')
  const reports = room.getByRole('group', { name: 'Reports' })
  await expect(reports).toContainText('Looked at it: fine.')
  await expect(room).not.toContainText('its work is over')

  // On the canvas the room is a node of its own, beside the lead and its two members.
  await expect(page.locator('.react-flow__node-room')).toHaveCount(1)
  await expect(page.locator('.react-flow__node-room')).toContainText('Look at the greeting together')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(3)
  await shot(page, '29b-room-asks')

  // You write into the room, and answer the Coder.
  const said = room.getByRole('group', { name: 'Said in the room' })
  await room.getByLabel('Say something in the room').fill('Keep it short.')
  await room.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(said).toContainText('Keep it short.')
  await waiting.getByLabel('Your answer').fill('Yes')
  await waiting.getByRole('button', { name: 'Send answer' }).click()

  // The Coder closes its item, everybody's work is over, and the room ends: the same window says what came of it.
  await expect(room.getByText('done · 1 of 1')).toBeVisible({ timeout: 20_000 })
  await expect(room.locator('.room-summary')).toHaveText('It prints hi, and stays so.')
  await expect(items).toContainText('✓ done1. Look at the greetingCoder')
  await expect(said).not.toHaveAttribute('open')
  await said.locator('summary').click()
  await expect(said).toContainText('Yes') // your answer is the room's too
  await expect(room.getByLabel('Say something in the room')).toHaveCount(0)
  await expect(room.getByRole('button', { name: 'End', exact: true })).toHaveCount(0)
  await shot(page, '29b-room-ended')

  // The lead took no part: it is given what came of the room, and has the turn's last word in the chat.
  await expect(chat.getByText('The room is over: the greeting stays hi.')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()

  // A reload shows the same room from the records; its line in the chat opens its window again.
  await page.reload()
  const again = page.getByRole('region', { name: 'Chat' })
  await expect(page.getByRole('dialog')).toHaveCount(0) // an ended room opens only at your word
  await again.getByRole('button', { name: /^Room · Look at the greeting together done · 1 of 1 · Open/ }).click()
  const reopened = page.getByRole('dialog', { name: 'Room: Look at the greeting together' })
  await expect(reopened.getByRole('region', { name: 'Items' })).toContainText('✓ done1. Look at the greetingCoder')
  await expect(reopened.locator('.room-summary')).toHaveText('It prints hi, and stays so.')
  await expect(reopened.getByRole('group', { name: 'Said in the room' })).toContainText('Keep it short.')
  await expect(reopened.getByRole('group', { name: 'Spent of its budget' })).toContainText('1 of 12 posts')
})
