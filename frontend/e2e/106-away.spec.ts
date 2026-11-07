// Slice 106 in the browser: "work while I'm away". Told the user goes to sleep, the Lead puts the
// night's jobs on a card, and nothing starts before the user's Start. Each job then runs in a chat
// of its own; at the end the chat the card was in has one line, the To-do page shows the night and
// each job as it came out, and KOLONİ opened afterwards goes to the morning's report: a node on the
// canvas, the jobs' frames leading to it - once.
import { expect, test, type Locator } from './fixtures'
import { contrasts, openFreshConversation, rail, say, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

async function reads(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

test('the night is on a card until Start; its jobs run in chats of their own; the morning opens on the report', async ({ page }) => {
  await openFreshConversation(page)
  await say(page, "I'm going to sleep, 106: add a bye line and say hello twice", 'The card is up: press Start when you go.')
  const card = page.getByRole('region', { name: "While you're away" })
  await expect(card).toContainText('Add a bye line, 106')
  await expect(card).toContainText('it prints bye')
  await expect(card).toContainText('Kept out: secret106')
  await reads(card, 8)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-card')

  // Started, the night is followed on the To-do page: the report is not on screen yet.
  await card.getByRole('button', { name: 'Start' }).click()
  await rail(page, 'To-do').click()
  await expect(page.getByRole('heading', { name: 'To-do' })).toBeVisible()
  const night = page.getByRole('region', { name: "While you're away" })
  await expect(night).toContainText('☾ While you were away: 2 of 2 done', { timeout: 30_000 })
  // Nothing of it waits for the user: it is one line, which opens on its jobs.
  await night.getByText('☾ While you were away: 2 of 2 done').click()
  await expect(night.getByRole('listitem', { name: 'Add a bye line, 106: Done' })).toBeVisible()
  await expect(night.getByRole('listitem', { name: 'Say hello twice, 106: Done' })).toBeVisible()
  await reads(night, 6)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-todo')

  // The morning: KOLONİ opened again - on another chat - goes to the night's report on the canvas.
  await openFreshConversation(page)
  const report = page.locator('.away-node')
  // (The scripted jobs change no file: nothing waits for Take in, and each says so - B-122.)
  await expect(report.locator('.away-sums .away-done')).toHaveText('2 done', { timeout: 10_000 })
  await expect(report.getByText('Done, nothing changed')).toHaveCount(2)
  await expect(page.locator('.react-flow__node-awayjob')).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('While you were away: 2 done - on the canvas')).toBeVisible()
  await reads(report, 6)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-report')

  // B-149: at 1219 px the inspector opened on the Lead narrows the canvas - the report stays in view.
  // (And with the chat made taller, as live: the report is kept clear of it too, in the strip above it.)
  await page.setViewportSize({ width: 1219, height: 700 })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  const height = page.getByRole('separator', { name: 'Chat height' })
  for (const taller of [0, 4]) {
    for (let step = 0; step < taller; step++) await height.press('ArrowUp')
    await page.getByRole('button', { name: 'Fit View' }).click()
    if (taller && process.env.KOLONI_SHOTS) await shot(page, 'b149-before')
    await page.locator('.react-flow__node-agent .node-title').first().click()
    await expect(inspector).toBeVisible()
    await expect
      .poll(async () => {
        const [node, stage, chat, teams] = [await report.boundingBox(), await page.locator('.canvas-flow').boundingBox(), await page.locator('.chat').boundingBox(), await page.locator('.chat-teams').boundingBox()]
        // (R73: nor under the chat's teams button in the corner.)
        const clear = !!node && !!chat && !!teams && (node.x >= chat.x + chat.width || node.y + node.height <= chat.y) && (node.x + node.width <= teams.x || node.y >= teams.y + teams.height)
        return clear && !!stage && node.x >= stage.x - 1 && node.x + node.width <= stage.x + stage.width + 1 && node.y >= stage.y - 1 && node.y + node.height <= stage.y + stage.height + 1
      })
      .toBe(true)
    if (taller && process.env.KOLONI_SHOTS) await shot(page, 'b149-after')
    await inspector.getByRole('button', { name: 'Close inspector' }).click()
  }
  for (let step = 0; step < 4; step++) await height.press('ArrowDown')

  // B-150: a job's chat, opened from the report, leads back to it - and so does the browser's Back.
  const chat = page.getByRole('region', { name: 'Chat' })
  const from = chat.getByRole('button', { name: /^From the jobs started at \d\d:\d\d while you were away — back to their report$/ })
  await report.getByRole('button', { name: 'Open its chat' }).first().click()
  await expect(from).toBeVisible()
  await expect(report).toHaveCount(0)
  await page.goBack()
  await expect(report).toBeVisible()
  await expect(chat.getByText('While you were away: 2 done - on the canvas')).toBeVisible()
  await report.getByRole('button', { name: 'Open its chat' }).first().click()
  await from.click()
  await expect(report).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 900 })
  // Seen once, it is not gone to again.
  await openFreshConversation(page)
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Send a message to start.')).toBeVisible()
  await expect(page.locator('.away-node')).toHaveCount(0)
})
