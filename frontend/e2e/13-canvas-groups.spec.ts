import { expect, test, type Locator, type Page } from './fixtures'
import { openFreshConversation } from './helpers'

/** The Reviewer's group, by its title (the lead's group may name the Reviewer as the one it waits for). */
const reviewerGroup = (page: Page) =>
  page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Reviewer$/ }) })

/** Where each node is on the canvas (React Flow places every node by a transform) and whether it shows. */
async function placed(page: Page) {
  return page.locator('.react-flow__node').evaluateAll(all =>
    Object.fromEntries(
      all.map(n => {
        const el = n as HTMLElement
        const [x, y] = (el.style.transform.match(/-?[\d.]+/g) ?? []).map(Number)
        return [el.dataset.id ?? '', { x, y, shown: el.style.visibility }]
      }),
    ),
  )
}

/** Wait until the view has finished fitting itself to the work. */
async function settled(page: Page) {
  const viewport = () => page.locator('.react-flow__viewport').evaluate(el => (el as HTMLElement).style.transform)
  let last = ''
  await expect
    .poll(
      async () => {
        const [was, now] = [last, await viewport()]
        last = now
        return was === now
      },
      { intervals: [300] },
    )
    .toBe(true)
}

async function drag(page: Page, handle: Locator, dx: number, dy: number, during?: () => Promise<void>) {
  const box = await handle.boundingBox()
  if (!box) throw new Error('nothing to take hold of')
  await page.mouse.move(box.x + box.width / 2, box.y + 12)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + dx, box.y + 12 + dy, { steps: 8 })
  await during?.()
  await page.mouse.up()
}

test('the user’s (5 Nov): two agents are two small nodes - what each did is counted on it, and the side panel shows it', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()

  // Joined by the line of the hand-off; three lines each at most, nothing inside.
  const agents = page.locator('.react-flow__node-agent')
  const reviewer = reviewerGroup(page)
  await expect(agents).toHaveCount(2)
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await expect(reviewer.locator('.node-head')).toContainText('Reviewer')
  await expect(reviewer.locator('.node-body > *')).toHaveText(['Done ✓', '1 tool'])
  await expect(page.getByRole('button', { name: /^(Expand|Collapse) Reviewer$/ })).toHaveCount(0)
  // every agent node is as tall as the others
  const heights = await agents.evaluateAll(all => all.map(n => Math.round(n.getBoundingClientRect().height)))
  expect(new Set(heights).size).toBe(1)

  // Dragged, it moves alone.
  await settled(page)
  const before = await placed(page)
  const ids = Object.keys(before)
  const reviewerId = ids.find(id => id.startsWith('agent:') && before[id].x > 400)!
  await drag(page, reviewer, 70, 50, async () => {
    expect(Object.values(await placed(page)).map(p => p.shown)).toEqual(ids.map(() => 'visible'))
  })
  const moved = await placed(page)
  expect(moved[reviewerId].x - before[reviewerId].x).toBeGreaterThan(20)
  for (const id of ids.filter(one => one !== reviewerId)) expect(moved[id]).toEqual(before[id])

  // Picked, the side panel shows its report card: who asked it what.
  await reviewer.getByText('Reviewer', { exact: true }).click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByText('Review hello.py')).toBeVisible()
})

test('an agent that waits for your answer is lit, and says so on its state line', async ({ page }) => {
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('review the greeting carefully')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()

  const reviewer = reviewerGroup(page)
  await expect(reviewer).toContainText('Waits for your answer')
  await expect(reviewer.locator('.node')).toHaveClass(/node-approval/)

  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'strict', exact: true }).click()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
})
