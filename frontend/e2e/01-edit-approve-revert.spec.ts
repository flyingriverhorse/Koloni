import { expect, test } from './fixtures'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const hello = () => readFileSync(path.join(PROJECT_DIR, 'hello.py'), 'utf8')

test('ask the agent for an edit, approve it, see it on disk, then revert it', async ({ page }) => {
  // The Lead writes the file itself here: a conversation with slice 48's default switched off.
  await openFreshConversation(page)

  await page.getByLabel('Message').fill('say hello instead of hi')
  await page.getByRole('button', { name: 'Send' }).click()

  // The agent reads the file, then proposes an edit and waits for a decision.
  await expect(page.getByText('read_file hello.py').first()).toBeVisible()
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  const changes = page.getByRole('region', { name: 'Workspace' })
  await expect(changes.getByText("print('hello')")).toBeVisible()
  expect(hello()).toBe("print('hi')\n")

  await changes.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByText('Updated the greeting in hello.py.')).toBeVisible()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
  await expect(page.getByText('in 120 · out 54').first()).toBeVisible()
  expect(hello()).toBe("print('hello')\n")

  // The canvas shows the work as real records: You and the Agent (its tools and files are in its panel).
  await expect(page.locator('.react-flow__node')).toHaveCount(2)

  // A reload rebuilds the same view from the server.
  await page.reload()
  await expect(page.getByText('Updated the greeting in hello.py.')).toBeVisible()
  await expect(page.locator('.react-flow__node')).toHaveCount(2)

  // Dragging one node by hand moves that node; the other stays, and both stay in sight.
  const nodes = page.locator('.react-flow__node')
  const placed = () =>
    nodes.evaluateAll(all => all.map(n => `${(n as HTMLElement).style.visibility}|${(n as HTMLElement).style.transform}`))
  const viewport = () => page.locator('.react-flow__viewport').evaluate(el => (el as HTMLElement).style.transform)
  // Wait until the view has finished fitting itself to the work.
  let last = ''
  await expect
    .poll(async () => {
      const [was, now] = [last, await viewport()]
      last = now
      return was === now
    }, { intervals: [300] })
    .toBe(true)
  const before = await placed()
  const grabbed = await nodes.nth(1).boundingBox()
  if (!grabbed) throw new Error('the node has no place on screen')
  await page.mouse.move(grabbed.x + grabbed.width / 2, grabbed.y + 12)
  await page.mouse.down()
  await page.mouse.move(grabbed.x + grabbed.width / 2 + 8, grabbed.y + 60, { steps: 6 })
  const held = await placed()
  expect(held.map(p => p.split('|')[0])).toEqual(['visible', 'visible'])
  await page.mouse.up()
  const after = await placed()
  expect(after[1]).not.toBe(before[1])
  expect(after[0]).toBe(before[0])

  await page.getByRole('button', { name: /^Workspace/ }).click()
  await changes.getByRole('treeitem', { name: /^hello\.py modified/ }).click()
  await changes.getByRole('button', { name: 'Revert' }).click()
  await expect(changes.locator('.change-actions').getByText('Reverted', { exact: true })).toBeVisible()
  expect(hello()).toBe("print('hi')\n")
})

test('a message sent while the agent waits is queued, and rejecting lets it run', async ({ page }) => {
  const before = hello()
  await openFreshConversation(page)

  await page.getByLabel('Message').fill('change the greeting again')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()

  await page.getByLabel('Message').fill('hello there')
  await page.getByRole('button', { name: 'Queue' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText('Queued')).toBeVisible()

  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible()
  // The queued message runs next, on its own.
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  await expect(chat.getByText('Queued')).toHaveCount(0)
  expect(hello()).toBe(before)
})
