// Slice 49 in the browser: /plan turns Plan first on beside the permission level; a message
// then gets a plan card - who planned it, Edit, Approve, Reject with why - and a Plan node at
// the turn's start on the canvas. Approved as edited, the work turn carries the plan; turned
// down, nothing more runs. The card reads at 4.5 in both themes.
import { expect, test, type Locator } from './fixtures'
import { contrasts, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

async function reads(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: plan, edit and approve; plan and reject`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    const box = chat.getByRole('textbox', { name: 'Message' })
    const planFirst = chat.getByRole('switch', { name: 'Plan first' })
    await expect(planFirst).not.toBeChecked()
    await box.fill('/plan')
    await page.keyboard.press('Enter')
    await expect(planFirst).toBeChecked()
    await reads(chat.locator('.composer-plan'), 1)

    await box.fill('what does hello.py print?')
    await chat.getByRole('button', { name: 'Send' }).click()
    const card = chat.locator('.cmd-approval').filter({ hasText: 'Approve this plan?' })
    await expect(card).toBeVisible({ timeout: 20_000 })
    await expect(chat.getByText('PLAN: 1. Read hello.py.')).toBeVisible()
    // (a provider an earlier spec gave the strongest tier writes it, if there is one)
    await expect(card).toContainText(/Planned by .+ · (the team’s strongest model|this conversation’s model)/)
    // at the turn's start on the canvas
    await expect(page.locator('.react-flow__node-plan')).toContainText('proposed')
    await reads(card, 4)
    if (process.env.KOLONI_SHOTS) await shot(page, `49-card-${theme}`)

    await card.getByRole('button', { name: 'Edit' }).click()
    const plan = card.getByRole('textbox', { name: 'Plan' })
    await expect(plan).toHaveValue('PLAN: 1. Read hello.py. 2. Say what it prints.')
    await plan.fill('PLAN: 1. Read hello.py. 2. Say it in one line.')
    await card.getByRole('button', { name: 'Approve edited plan' }).click()
    await expect(chat.getByText('Plan approved: its work starts as a new turn.')).toBeVisible()
    await expect(chat.getByText(/The approved plan:\s*PLAN: 1\. Read hello\.py\. 2\. Say it in one line\./)).toBeVisible()
    await expect(chat.getByText('Done, as the approved plan said.')).toBeVisible({ timeout: 20_000 })
    // the work turn shows the plan it carries out, over its Lead; a click opens it in the panel
    const carried = page.locator('.react-flow__node-plan[data-id^="planned:"]')
    await expect(carried).toContainText('approved')
    // with its dashed line straight down to the Lead (drawn only if both its ends are there)
    await expect(page.locator('.react-flow__edge-straight[data-id^="planned:"]')).toHaveCount(1)
    await carried.click()
    await expect(page.getByText('Plan · approved')).toBeVisible()

    // another message plans again; turned down, it says why and nothing more runs
    await box.fill('and check.py?')
    await chat.getByRole('button', { name: 'Send' }).click()
    const next = chat.locator('.cmd-approval').filter({ hasText: 'Approve this plan?' })
    await expect(next).toBeVisible({ timeout: 20_000 })
    await next.getByRole('button', { name: 'Reject' }).click()
    await expect(next.getByRole('textbox', { name: 'Why not (optional)' })).toBeFocused()
    await page.keyboard.type('not now')
    await next.getByRole('button', { name: 'Reject plan' }).click()
    await expect(chat.getByText('Plan rejected: not now')).toBeVisible()
    await expect(chat.getByText('Done, as the approved plan said.')).toHaveCount(1)
  })
