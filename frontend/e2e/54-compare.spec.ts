// Slice 54 in the browser: a message sent to two models from Compare under More. Each side works
// in a working copy of its own - nothing reaches the project - and the two stand side by side under
// the message: answer, changed file with its diff, time, tokens, cost. "Use Rival's work" takes that
// side's file into the project, folds the other side's rows into one closed row, and can be undone;
// "Discard both" leaves the project as it was. Reads at 4.5 in both themes.
import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Locator } from './fixtures'
import { OWN, contrasts, more, openFreshConversation, shot } from './helpers'
import { MODEL_URL, PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const FILE = path.join(PROJECT_DIR, 'greeting54.txt')

async function reads(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

/** A second provider on the same stand-in server, asked for a model of another name: it answers as that one. */
async function second(request: APIRequestContext) {
  // (Its own name: an earlier spec leaves a provider called "Second" with another model behind.)
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  if (listed.some(p => p.name === 'Rival')) return
  const made = await request.post('/api/providers', {
    data: { name: 'Rival', kind: 'openai_compat', base_url: `${MODEL_URL}/v1`, default_model: 'fake-other' },
    headers: OWN,
  })
  expect(made.ok()).toBe(true)
}

test.afterAll(async ({ request }) => {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === 'Rival')) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  rmSync(FILE, { force: true })
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: two models side by side, one kept and undone, or both thrown away`, async ({ page, request }) => {
    rmSync(FILE, { force: true })
    await second(request)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // (with the Lead handing code to sub-agents, as by default: a side's Lead does its work itself)
    const cid = await openFreshConversation(page, { leadWrites: false })
    expect((await page.request.patch(`/api/conversations/${cid}`, { data: { permission_mode: 'full_auto' }, headers: OWN })).ok()).toBe(true)
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('textbox', { name: 'Message' }).fill('compare the greeting')
    await more(page)
    await chat.getByRole('button', { name: 'Compare…' }).click()
    const form = chat.getByRole('form', { name: 'Compare two models' })
    await expect(form.getByLabel('Message')).toHaveValue('compare the greeting')
    await form.getByLabel('Second model’s provider').selectOption({ label: 'Rival' })
    await reads(form, 3)
    // Its notes wrap in it: nothing runs off sideways (opened from More, whose row does not wrap).
    expect(await form.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0)
    await form.getByRole('button', { name: 'Compare' }).click()

    const compared = chat.getByRole('group', { name: 'Two models compared' })
    const first = compared.getByRole('region', { name: /^Local/ })
    const other = compared.getByRole('region', { name: /^Rival/ })
    await expect(first).toContainText('Wrote the greeting as', { timeout: 20_000 })
    await expect(other).toContainText('Wrote the greeting as fake-other', { timeout: 20_000 })
    // Side by side in this chat too (480 px), and one turn on the canvas: one "You", the two Leads under it.
    const tops = await compared.locator('.compare-side').evaluateAll(all => all.map(side => side.getBoundingClientRect().top))
    expect(tops).toEqual([tops[0], tops[0]])
    await expect(page.locator('.react-flow__node-request')).toHaveCount(1)
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
    // the message once; neither side's file in the project
    await expect(chat.getByText('compare the greeting', { exact: true })).toHaveCount(1)
    expect(existsSync(FILE)).toBe(false)
    await expect(other.getByRole('list', { name: /Files Rival/ })).toContainText('greeting54.txt')
    await expect(other).toContainText(/Tokens\s*in \d/)
    await expect(other).toContainText('Cost –')
    await other.getByText('View diff').click()
    await expect(other.locator('.merge-file-diff')).toContainText('hello from fake-other')
    await reads(compared, 10)
    if (process.env.KOLONI_SHOTS) await shot(compared, `54-compare-${theme}`)

    await compared.getByRole('button', { name: 'Use Rival’s work' }).click()
    await expect(compared.getByRole('status')).toContainText('Rival’s work was taken')
    await expect.poll(() => existsSync(FILE) && readFileSync(FILE, 'utf8')).toBe('hello from fake-other\n')
    await expect(other.getByText('Chosen')).toBeVisible()
    await expect(compared.getByRole('button', { name: /^Use / })).toHaveCount(0)
    await reads(compared, 6)
    // What the side not used did is one closed row; the used side's stands as it was.
    const folded = chat.locator('details', { hasText: 'The other side (not used)' })
    await expect(folded).toHaveCount(1)
    await expect(folded).not.toHaveAttribute('open')
    await expect(chat.getByRole('separator').filter({ hasText: /^Rival.*’s work$/ })).toHaveCount(1)
    await reads(folded, 1)
    if (process.env.KOLONI_SHOTS) {
      await folded.scrollIntoViewIfNeeded()
      await shot(chat, `54-other-side-${theme}`)
    }

    // The pick undone: the chosen side's file is taken back out of the project.
    await compared.getByRole('button', { name: 'Undo these changes' }).click()
    const undo = compared.getByRole('region', { name: 'Undo these changes' })
    await expect(undo).toContainText('greeting54.txt')
    await reads(undo, 3)
    if (process.env.KOLONI_SHOTS) await shot(undo, `54-undo-${theme}`)
    await undo.getByRole('button', { name: 'Undo', exact: true }).click()
    await expect(undo).toContainText('Undo these changes: done')
    await expect.poll(() => existsSync(FILE)).toBe(false)

    if (theme === 'dark') {
      // A second comparison, both thrown away: nothing reaches the project.
      await chat.getByRole('textbox', { name: 'Message' }).fill('compare the greeting again')
      await more(page)
      await chat.getByRole('button', { name: 'Compare…' }).click()
      await form.getByLabel('Second model’s provider').selectOption({ label: 'Rival' })
      await form.getByRole('button', { name: 'Compare' }).click()
      const again = chat.getByRole('group', { name: 'Two models compared' }).last()
      await expect(again.getByRole('region', { name: /^Rival/ })).toContainText('Wrote the greeting as fake-other', { timeout: 20_000 })
      await again.getByRole('button', { name: 'Discard both' }).click()
      await expect(again.getByRole('status')).toContainText('Both were thrown away')
      expect(existsSync(FILE)).toBe(false)
    }
  })
