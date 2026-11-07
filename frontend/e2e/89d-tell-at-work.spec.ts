import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { APIRequestContext, Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { OWN, openFreshConversation } from './helpers'
import { E2E_ROOT, FAKE_CLAUDE } from './paths.mjs'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'sd-shots')
// The stand-in Claude Code's plan (start-backend.mjs): this spec's own for its test, put back after it.
const PLAN = path.join(E2E_ROOT, 'claude-plan.json')
const RECORD = path.join(E2E_ROOT, 'claude-tell-record.json')

async function removeClaudeCode(request: APIRequestContext) {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === 'Claude Code')) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

/** Light and dark, as the theme button sets them. */
async function both(page: Page, target: Locator, name: string) {
  await target.screenshot({ path: path.join(SHOTS, `${name}-light.png`) })
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await target.screenshot({ path: path.join(SHOTS, `${name}-dark.png`) })
  await page.evaluate(() => document.documentElement.classList.remove('dark'))
}

// 89d C: the user's own word to an agent while it works, from its window - into Claude Code's turn as a user line.
test.describe('telling Claude Code something while it works', () => {
  let kept = ''

  test.beforeEach(async ({ page, request }) => {
    mkdirSync(SHOTS, { recursive: true })
    kept = readFileSync(PLAN, 'utf8')
    // It says a word, waits for a line from KOLONİ, and takes a moment over it before it answers.
    writeFileSync(PLAN, JSON.stringify({ record: RECORD, script: [{ say: 'Working on it.' }, { await_steer: 60 }, { sleep: 4 }, { say: 'Blue it is.' }] }))
    await removeClaudeCode(request)
    const id = await openFreshConversation(page)
    const patched = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })
    expect(patched.ok()).toBe(true)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill('Claude Code')
    await page.getByLabel('Kind').selectOption({ label: 'Claude Code (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_CLAUDE)
    await page.getByLabel('How it runs').selectOption('native')
    await page.getByRole('button', { name: 'Add provider' }).click()
    await expect(page.getByRole('button', { name: /^Claude Code/ })).toBeVisible()
  })

  test.afterEach(async ({ request }) => {
    writeFileSync(PLAN, kept)
    await removeClaudeCode(request)
  })

  test('Tell … under its window while it works; said sent; gone once its work is over', async ({ page }) => {
    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Model: Local/ }).click()
    await chat.getByLabel('Provider').selectOption({ label: 'Claude Code' })
    await chat.getByRole('button', { name: 'Use this model' }).click()
    await expect(chat.getByRole('button', { name: /^Model: Claude Code/ })).toBeVisible()
    await page.getByRole('textbox', { name: 'Message' }).fill('make the button a nice colour')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('Working on it.')).toBeVisible()

    // An agent that works with its own tools has its window open.
    const window = page.getByRole('region', { name: 'Agent window' })
    const tell = window.getByRole('textbox', { name: /^Tell / })
    await expect(tell).toBeVisible()
    await tell.fill('use blue')
    await both(page, window, 'tell-typed')
    await window.getByRole('button', { name: /^Send to / }).click()
    await expect(window.getByRole('status').filter({ hasText: /^Sent to .+ while it works$/ })).toBeVisible()
    await both(page, window, 'tell-sent')
    const record = () => JSON.parse(readFileSync(RECORD, 'utf8'))
    await expect.poll(() => record().steered?.length ?? 0).toBe(1)
    expect(record().steered[0].message.content).toContain('The user tells you while you work - their own word: "use blue"')

    // Its work over: nothing more to tell it here.
    await expect(chat.getByText('Blue it is.')).toBeVisible()
    await expect(tell).toHaveCount(0)
  })
})
