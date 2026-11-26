// Slice 106 in the browser, as ☾ Away: told the user goes to sleep, the Orchestrator puts the work on To-do and offers
// one line to go away; nothing starts before Go away. Change opens the Away panel there; Go away works the To-do
// through, each task in a chat of its own, the status line saying where it stands; I'm back writes one summary in the
// chat, the To-do page shows the same, and the report is on the canvas - which KOLONİ goes to once.
import { expect, test, type Locator } from './fixtures'
import { contrasts, openFreshConversation, rail, say, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

async function reads(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

test('the work goes on To-do with a Go away line; Away works it through until I’m back; one summary, the report on the canvas', async ({
  page,
}) => {
  test.setTimeout(90_000)
  await openFreshConversation(page)
  await say(
    page,
    "I'm going to sleep, 106: add a bye line and say hello twice",
    'Two tasks are on your To-do: press Go away when you go.',
  )
  const chat = page.getByRole('region', { name: 'Chat' })
  const offer = chat.getByRole('group', { name: 'Go away now?' })
  await expect(offer).toContainText('kept out secret106')
  await reads(offer, 2)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-offer')

  // Change: the Away panel, here - both new tasks ticked; the second moved up; Go away.
  await offer.getByRole('button', { name: 'Change' }).click()
  await expect(chat.getByRole('checkbox', { name: 'Add a bye line, 106' })).toBeChecked()
  await expect(chat.getByRole('checkbox', { name: 'Say hello twice, 106' })).toBeChecked()
  await chat.getByRole('button', { name: 'Move Say hello twice, 106 up' }).click()
  await reads(chat.locator('.away-panel-body'), 8)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-panel')
  await chat.getByRole('button', { name: 'Go away' }).click()

  // While away, the status line says where To-do stands, and the chip is I'm back.
  const line = page.locator('.composer-status')
  await expect(line).toContainText(/Away · To-do (\d of 2|2 of 2 looked at)/, { timeout: 30_000 })
  await expect(line).toContainText('Away · To-do 2 of 2 looked at', { timeout: 30_000 })
  await expect(page.getByLabel('Message')).toHaveAttribute('placeholder', 'Write to come back…')

  // The To-do page shows the same.
  await rail(page, 'To-do').click()
  await expect(page.getByRole('heading', { name: 'To-do' })).toBeVisible()
  const night = page.getByRole('region', { name: "While you're away" })
  await expect(night).toContainText('2 of 2 done')
  await reads(night, 2)
  await page.getByRole('button', { name: 'I’m back' }).first().click()
  await rail(page, 'Canvas').click()

  // Back: one summary in the chat - its span, both done.
  const summary = chat.getByRole('region', { name: 'While you were away' })
  await expect(summary.getByRole('heading')).toHaveText(/While you were away \(\d\d:\d\d – \d\d:\d\d\)/, {
    timeout: 10_000,
  })
  await expect(summary).toContainText('2 of 2 To-do done')
  await reads(summary, 4)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-summary')

  // The morning (M1): KOLONİ opened again opens Ready for you, on the night - and its whole report is on the canvas.
  await page.reload()
  const strip = page.getByRole('region', { name: /^Last night/ })
  await expect(strip).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('heading', { name: /^Ready for you/ })).toBeVisible()
  await strip.getByRole('button', { name: 'The whole report' }).click()
  await expect(page.locator('.away-node')).toBeVisible()

  // On the canvas: the report, the jobs' frames leading to it.
  await summary.getByRole('button', { name: 'On the canvas' }).click()
  const report = page.locator('.away-node')
  // (The scripted jobs change no file: nothing waits for Take in, and each says so - B-122.)
  await expect(report.locator('.away-sums .away-done')).toHaveText('2 done', { timeout: 10_000 })
  await expect(report.getByText('Done, nothing changed')).toHaveCount(2)
  await expect(page.locator('.react-flow__node-awayjob')).toHaveCount(2)
  await reads(report, 6)
  if (process.env.KOLONI_SHOTS) await shot(page, '106-report')

  // B-149: at 1219 px the inspector opened on the Lead narrows the canvas - the report stays in view.
  // (And with the chat made wider: the report is kept clear of it too, beside it.)
  await page.setViewportSize({ width: 1219, height: 700 })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  const width = page.getByRole('separator', { name: 'Chat width' })
  for (const wider of [0, 4]) {
    for (let step = 0; step < wider; step++) await width.press('ArrowRight')
    await page.getByRole('button', { name: 'Fit View' }).click()
    await page.locator('.react-flow__node-agent .node-title').first().click()
    await expect(inspector).toBeVisible()
    await expect
      .poll(async () => {
        const [node, stage, box, teams] = [
          await report.boundingBox(),
          await page.locator('.canvas-flow').boundingBox(),
          await page.locator('.chat').boundingBox(),
          await page.locator('.chat-teams').boundingBox(),
        ]
        // (R73: nor under the chat's teams button in the corner.)
        const clear =
          !!node &&
          !!box &&
          !!teams &&
          (node.x >= box.x + box.width || node.y + node.height <= box.y) &&
          (node.x + node.width <= teams.x || node.y >= teams.y + teams.height)
        return (
          clear &&
          !!stage &&
          node.x >= stage.x - 1 &&
          node.x + node.width <= stage.x + stage.width + 1 &&
          node.y >= stage.y - 1 &&
          node.y + node.height <= stage.y + stage.height + 1
        )
      })
      .toBe(true)
    await inspector.getByRole('button', { name: 'Close inspector' }).click()
  }
  for (let step = 0; step < 4; step++) await width.press('ArrowLeft')

  // B-150: a job's chat, opened from the report, leads back to it - and so does the browser's Back.
  const from = chat.getByRole('button', {
    name: /^From the jobs started at \d\d:\d\d while you were away — back to their report$/,
  })
  await report.getByRole('button', { name: 'Open its chat' }).first().click()
  await expect(from).toBeVisible()
  await expect(report).toHaveCount(0)
  await page.goBack()
  await expect(report).toBeVisible()
  await expect(summary).toBeVisible()
  await report.getByRole('button', { name: 'Open its chat' }).first().click()
  await from.click()
  await expect(report).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 900 })
  // Seen once, it is not gone to again.
  await openFreshConversation(page)
  await expect(chat.getByText('Send a message to start.')).toBeVisible()
  await expect(page.locator('.away-node')).toHaveCount(0)
})
