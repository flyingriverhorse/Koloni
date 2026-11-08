import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, shot, agentFold } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const ALPHA = path.join(PROJECT_DIR, 'alpha.txt')
const BETA = path.join(PROJECT_DIR, 'beta.txt')
/** The files this spec's turns write are not left behind: the specs share the backend. */
const CONFIG = path.join(PROJECT_DIR, 'config')
const tidy = () => [ALPHA, BETA, CONFIG].forEach(file => rmSync(file, { recursive: true, force: true }))
test.beforeEach(tidy)
test.afterEach(tidy)

async function twoCoders(page: import('@playwright/test').Page) {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(page.getByRole('button', { name: 'This chat’s settings' })).toBeAttached() // (⚙ Chat: there with a chat)
  await page.getByLabel('Permission level').selectOption('ask')
  await expect(page.getByLabel('Permission level')).toHaveValue('ask')
  await page.getByLabel('Message').fill('two coders in their own copies')
  await page.getByRole('button', { name: 'Send' }).click()
  for (const _ of [1, 2]) await chat.getByRole('button', { name: 'Open agent' }).first().click()
  // The quick one is done and asks; the other has written its file in its copy and is at work.
  await expect(chat.getByText("Take in Coder 2's work? · 1 file")).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) })).toContainText('1 file')
  return chat
}

test('a file that changed in the project meanwhile stands apart on the card, and what you discard says so', async ({ page }) => {
  const chat = await twoCoders(page)
  // Meanwhile the same file appears in the project, by the user's own hand.
  writeFileSync(ALPHA, 'mine\n')
  await chat.getByRole('button', { name: 'Take in', exact: true }).click()

  const card = chat.getByText("Take in Coder's work? · 1 file")
  await expect(card).toBeVisible({ timeout: 15_000 })
  // Both sides made the file anew: there is nothing to merge it by, and whose file is taken is asked.
  const apart = chat.getByRole('group', { name: 'Changed on both sides' })
  await expect(apart).toContainText('alpha.txt — changed in the project meanwhile, and not merged line by line: both sides made it anew')
  await expect(apart.getByRole('radio', { name: "Take Coder's file" })).not.toBeChecked()
  await expect(apart.getByRole('radio', { name: "Keep the project's file" })).not.toBeChecked()
  await expect(chat.getByRole('button', { name: 'Take in', exact: true })).toBeDisabled()
  await apart.locator('.merge-file-path', { hasText: 'alpha.txt' }).click()
  await expect(apart.locator('.diff-del')).toContainText('mine')
  await shot(page, '19c-card-with-a-conflict')

  // Discard: the project's file stays, and the line under the agent says why its change is not there.
  await chat.getByRole('button', { name: 'Discard' }).click()
  const lines = chat.getByRole('group', { name: "Not all of Coder's work reached the project" })
  await expect(lines).toContainText('alpha.txt — you discarded it', { timeout: 15_000 })
  await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 15_000 })
  expect(readFileSync(ALPHA, 'utf8')).toBe('mine\n')
  await shot(page, '19c-not-applied-lines')
})

for (const theme of ['light', 'dark'] as const) {
  test(`B-56 (${theme}): a file that changed since you looked is not written over - Apply takes nothing, says why and shows the card as it is now`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const chat = await twoCoders(page)
    await chat.getByRole('button', { name: 'Take in', exact: true }).click()
    await expect(chat.getByText("Take in Coder's work? · 1 file")).toBeVisible({ timeout: 20_000 })
    await expect(chat.getByRole('group', { name: 'Files to take in' })).toContainText('alpha.txt')
    // While the card waits, the same file appears in the project by the user's own hand.
    writeFileSync(ALPHA, 'mine\n')
    await chat.getByRole('button', { name: 'Take in', exact: true }).click()
    await expect(chat.getByRole('alert')).toHaveText('alpha.txt changed since you looked: nothing was taken in. Check the card again')
    const apart = chat.getByRole('group', { name: 'Changed on both sides' })
    await expect(apart).toContainText('alpha.txt')
    await expect(chat.getByRole('button', { name: 'Take in', exact: true })).toBeDisabled()
    expect(readFileSync(ALPHA, 'utf8')).toBe('mine\n')
    await shot(page, `19c-changed-since-you-looked-${theme}`)

    await apart.getByRole('radio', { name: "Keep the project's file" }).check()
    await chat.getByRole('button', { name: 'Take in', exact: true }).click()
    await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 15_000 })
    expect(readFileSync(ALPHA, 'utf8')).toBe('mine\n')
  })

  test(`K-dikkat-satiri (${theme}): a config file the agent wrote is worth a look - the card says why and which file, no score`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(page.getByRole('button', { name: 'This chat’s settings' })).toBeAttached() // (⚙ Chat: there with a chat)
    await page.getByLabel('Permission level').selectOption('ask')
    await expect(page.getByLabel('Permission level')).toHaveValue('ask')
    await page.getByLabel('Message').fill('a coder on the config file')
    await page.getByRole('button', { name: 'Send' }).click()
    await chat.getByRole('button', { name: 'Open agent' }).click()
    await expect(chat.getByText("Take in Coder's work? · 1 file")).toBeVisible({ timeout: 15_000 })
    const look = chat.getByRole('note', { name: 'Worth a look' })
    await expect(look).toHaveText('Worth a look config or env: config/app.yaml')
    expect((await look.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `19c-worth-a-look-${theme}`)
    await chat.getByRole('button', { name: 'Discard' }).click()
    await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 15_000 })
  })
}

test('Stop keeps the copies: their changes stay in the copy for you to take in, not rejected', async ({ page }) => {
  const chat = await twoCoders(page)
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  // The agent that was at work: what it had changed stays in its copy, behind a kept card.
  await chat.getByRole('button', { name: /^Coder Write alpha\.txt/ }).click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // (its Changes are open from the start)
  await expect(agentFold(inspector, 'Changes').locator('.chat-change', { hasText: 'alpha.txt' })).toContainText('In its copy')
  await page.waitForTimeout(400) // the canvas moves its view over a fifth of a second
  await shot(page, '19c-kept')
  // Leave nothing kept for the specs after this one (a kept copy holds a restore off): Discard each.
  const discard = chat.getByRole('button', { name: 'Discard' })
  for (let left = await discard.count(); left > 0; left = await discard.count()) {
    await discard.first().click()
    await expect(discard).toHaveCount(left - 1, { timeout: 15_000 })
  }
})
