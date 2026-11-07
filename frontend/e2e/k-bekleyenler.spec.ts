import { mkdirSync, existsSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot, setProject } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// K-bekleyenler, tek-ev §1: everything that waits for you is on Ready for you - the top bar's pill opens its panel,
// the open chat's first - and answered from there: a question, a decision (a command), then the recipe's copy ready
// for Take in. Nothing leaves the machine: the fake model plays it.
const RECIPE = 'Waits for you kb'
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'bekleyen-shots')
const B23 = path.join(os.tmpdir(), 'koloni-docs', 'b23-shots')

for (const theme of ['light', 'dark'] as const) {
  test(`a question, a command and a copy to take in are answered from Ready for you (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const file = path.join(PROJECT_DIR, `bekleyen-${theme}.txt`)
    rmSync(file, { force: true })
    const id = await openFreshConversation(page, { leadWrites: false })
    const graph = {
      version: 1,
      steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder' } }],
      ends: [{ id: 'end', then: 'in' }],
      arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
    }
    await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === RECIPE)
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
    // (Ask before changes: the command is asked about.)
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: { permission_mode: 'ask', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
    })
    expect(set.ok()).toBe(true)

    await page.getByLabel('Message').fill(`make it by the recipe, kb ${theme}`)
    await page.getByRole('button', { name: 'Send' }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    // (Other chats of the run may wait too: the panel's This chat is this one's.)
    const pill = page.locator('.ready-pill')
    const panel = page.getByRole('complementary', { name: /^Ready for you · \d+$/ })
    await expect(pill).toHaveText(/^\d+ waits?$/, { timeout: 20_000 })
    await pill.click()
    await expect(panel).toBeFocused()
    await expect(panel.getByRole('heading', { name: 'This chat · 1' })).toBeVisible()

    // A question, said by whom, and answered here.
    // (A question and a yes or no are both under Needs your answer: sample A.)
    const questions = panel.getByRole('region', { name: 'Needs your answer' })
    await expect(questions).toContainText('Coder asks')
    await expect(questions).toContainText('Which name for it?')
    mkdirSync(SHOTS, { recursive: true })
    await panel.screenshot({ path: path.join(SHOTS, `question-${theme}.png`) })
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    // The canvas's Ready for you says the same, in one line, and only points to the list (mockup Y, option 1).
    const node = page.locator('.ready-node')
    await expect(node).toContainText('1 question')
    await expect(node.locator('.tag')).toHaveText('1')
    await expect(node.getByRole('button', { name: 'Take in' })).toHaveCount(0)
    await questions.getByRole('button', { name: 'plain' }).click()

    // Then a decision: the command, run from here.
    const decisions = questions
    await expect(decisions).toContainText('python check.py', { timeout: 20_000 })
    await expect(questions).not.toContainText('Which name for it?')
    await panel.screenshot({ path: path.join(SHOTS, `decision-${theme}.png`) })
    await decisions.getByRole('button', { name: 'Run once' }).click()

    // Then the recipe's copy, ready: Take in from here, and it is in the project.
    const ready = panel.getByRole('region', { name: 'Ready to take in' })
    await expect(ready).toContainText('Take the work into the project?', { timeout: 20_000 })
    expect(existsSync(file)).toBe(false)
    // K-hazir-satir: in the chat the same card is one line, not titled Ready for you; details → is the card in the panel.
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    const line = chat.locator('.question-line')
    await expect(line).toContainText("Teams' work is ready · Web app 1 file")
    await expect(line).not.toContainText('Ready for you')
    await expect(line.getByRole('button', { name: 'Take in' })).toBeVisible()
    expect((await line.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    mkdirSync(B23, { recursive: true })
    await chat.screenshot({ path: path.join(B23, `chat-ready-line-${theme}.png`) })
    await line.getByRole('button', { name: 'details →' }).click()
    await expect(ready.getByRole('button', { name: 'Take in' })).toBeInViewport()
    await panel.screenshot({ path: path.join(SHOTS, `ready-${theme}.png`) })
    await expect(node).toContainText('1 copy to take in')
    await node.screenshot({ path: path.join(SHOTS, `canvas-node-${theme}.png`) })
    // The panel closed, the node's Open the list opens it again.
    await panel.getByRole('button', { name: 'Close Ready for you' }).click()
    await expect(panel).toBeHidden()
    await node.getByRole('button', { name: 'Open the list →' }).click()
    await expect(panel).toBeVisible()
    await shot(page, `k-bekleyenler-ready-${theme}`)
    await page.screenshot({ path: path.join(SHOTS, `canvas-and-list-${theme}.png`) })
    await ready.getByRole('button', { name: 'Take in' }).click()
    await expect(page.locator('.ready-node')).toContainText('In the project ✓', { timeout: 20_000 })
    expect(existsSync(file)).toBe(true)
    await expect(panel.getByText('Nothing waits for you.')).toBeVisible()
    await expect(panel.getByRole('heading', { name: 'This chat · 0' })).toBeVisible()
    await panel.screenshot({ path: path.join(SHOTS, `empty-${theme}.png`) })
    rmSync(file, { force: true })
  })
}
