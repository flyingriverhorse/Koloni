import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Page } from './fixtures'
import { contrasts, openFreshConversation, openAgentFold } from './helpers'
import { APP_URL, PROJECT_DIR, REPO_ROOT } from './paths.mjs'

const FACT = 'The service listens on port 8123.'
const SETTINGS = '# settings\nThe service listens on port 8123.\n'
const settings = path.join(PROJECT_DIR, 'settings.txt')
// What changes memory is taken only from the app's own page, which says where it is from.
const OWN = { Origin: APP_URL }

const rail = (page: Page, name: 'Memory' | 'Canvas') =>
  page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name, exact: true })

async function openWindowOf(page: Page, name: RegExp) {
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: name }) })
    .last().locator('.node-title').click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  return page.getByRole('region', { name: 'Agent window' })
}

/** Everything in effect or waiting goes to Past, so that each test (and the specs after) starts from an empty memory. */
async function clearMemory(request: APIRequestContext) {
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    const memory = await (await request.get(`/api/projects/${project.id}/memory`)).json()
    const ids = new Set<string>([...memory.proposals, ...memory.core, ...memory.journal].map((r: { id: string }) => r.id))
    for (const id of ids) await request.post(`/api/memory/${id}/reject`, { headers: OWN })
  }
}

/** The lead reads settings.txt and puts what line 2 says forward for the core. */
async function noteThePort(page: Page) {
  await page.getByLabel('Message').fill('note the port')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Noted where the port is set. It waits for you.')).toBeVisible({ timeout: 15_000 })
}

test.beforeEach(async ({ request }) => {
  await clearMemory(request)
  // Written before any turn of the test: a file that changed during a turn cannot back a fact.
  writeFileSync(settings, SETTINGS)
})

test.afterEach(async ({ request }) => {
  await clearMemory(request)
  writeFileSync(settings, SETTINGS)
})

test('a refused approval says why beside the note: its source changed (409), or the core is full (422)', async ({ page, request }) => {
  await openFreshConversation(page)
  await noteThePort(page)
  await rail(page, 'Memory').click()
  const waiting = page.getByRole('region', { name: 'Waits for you' })
  const core = page.getByRole('tabpanel', { name: /^Facts/ })
  const proposal = waiting.getByRole('article')
  await page.getByRole('button', { name: '● 1 fact waits for your word' }).click()
  await expect(proposal).toContainText(FACT)
  await expect(proposal).toContainText('source unchanged since noted')

  // The line it rests on changes on disk after the page read it: the server looks again and says no.
  writeFileSync(settings, '# settings\nThe service listens on port 9000.\n')
  await proposal.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(proposal.getByRole('alert')).toHaveText('source changed since it was noted: check again')
  await expect(proposal).toHaveCount(1)
  await expect(core.getByText(/Nothing is in the core yet/)).toBeVisible()

  // The file reads as it did again, but the core has no room left for it.
  writeFileSync(settings, SETTINGS)
  const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
  for (let n = 0; n < 8; n++) {
    const made = await request.post(`/api/projects/${project.id}/memory`, {
      headers: OWN,
      data: { text: `${n} ${'y'.repeat(496)}`, about: `filler ${n}` },
    })
    expect(made.status()).toBe(201)
  }
  await page.getByRole('button', { name: 'Look at the sources again' }).click()
  await expect(core.getByText('3 984 / 4 000 characters')).toBeVisible()
  await expect(proposal).toContainText('source unchanged since noted')
  await proposal.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(proposal.getByRole('alert')).toContainText('the core holds at most 4000 characters and has 3984')
  // Refused twice, it still waits; nothing entered the core beside what was written there.
  await expect(proposal).toHaveCount(1)
  await expect(core.getByRole('article')).toHaveCount(8)
  await expect(core.getByText(FACT)).toHaveCount(0)
})

test('the Memory page takes every colour from the theme: memory.css names none of its own', () => {
  const css = readFileSync(path.join(REPO_ROOT, 'frontend', 'src', 'theme', 'memory.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  expect(css).toContain('var(--surface)')
  // No hex, no rgb()/hsl()/color(), no colour by name: a fixed colour is right in one theme at most.
  expect(css.match(/#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|oklch|oklab|color|color-mix)\(/gi)).toBeNull()
  const values = Array.from(css.matchAll(/(?:^|[\s;{])(?:color|background(?:-color)?|border(?:-color)?|box-shadow|outline)\s*:\s*([^;}]+)/g)).map(m => m[1])
  expect(values.length).toBeGreaterThan(10)
  for (const value of values) {
    expect(value.replace(/var\(--[\w-]+\)/g, '')).not.toMatch(/\b(white|black|gr[ae]y|red|green|blue|yellow|orange|purple|silver)\b/)
  }
})

test('in the dark theme every text of the Memory page stands out from what it is on (contrast 4.5 or more)', async ({ page, request }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'dark'))
  await openFreshConversation(page)
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  // Something in every part of the page: a fact, one removed, rules, and a note that
  // would take the fact's place (the two side by side).
  const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
  const write = (data: object) => request.post(`/api/projects/${project.id}/memory`, { headers: OWN, data })
  expect((await write({ text: 'The service listens on port 8000.', about: 'port', file: 'settings.txt', start_line: 1 })).status()).toBe(201)
  const gone = await write({ text: 'The host is example.', about: 'host' })
  await request.post(`/api/memory/${(await gone.json()).id}/reject`, { headers: OWN })
  await request.put(`/api/projects/${project.id}/rules`, { headers: OWN, data: { rules: 'Sign every commit.' } })
  try {
    await noteThePort(page)
    await rail(page, 'Memory').click()
    const memory = page.locator('.memory-page')
    await page.getByRole('button', { name: '● 1 fact waits for your word' }).click()
    await expect(page.getByRole('region', { name: 'Waits for you' }).getByRole('group', { name: 'Would replace' })).toBeVisible()
    // No colour is on its way from one theme to the other.
    await expect(page.locator('html')).not.toHaveClass(/theme-switching/)

    const shot = testInfo.outputPath('memory-dark.png')
    await memory.screenshot({ path: shot })
    await testInfo.attach('the Memory page in the dark theme', { path: shot, contentType: 'image/png' })

    // Each tab in turn, so that what is in every one is measured.
    const all: ReturnType<typeof contrasts> = []
    for (const name of ['Facts', 'Told', 'Notes', 'History']) {
      await page.getByRole('tab', { name: new RegExp(`^${name}`) }).click()
      all.push(...(await memory.evaluate(contrasts)))
    }
    await expect(page.getByRole('region', { name: 'Removed / replaced' }).getByRole('article')).not.toHaveCount(0)
    await expect(page.getByRole('region', { name: 'Recent decisions' }).getByRole('listitem')).not.toHaveCount(0)
    const of = (cls: RegExp) => all.filter(piece => cls.test(piece.cls))
    // The three the page is made of: its main text and its muted text on a card, and
    // muted text on the page itself.
    expect(of(/\bmemory-text\b/).length).toBeGreaterThan(0)
    expect(of(/\bmemory-hint\b/).length).toBeGreaterThan(0)
    expect(of(/^span\..*\bmuted\b/).length).toBeGreaterThan(0)
    expect(all.length).toBeGreaterThan(40)
    expect(all.filter(piece => piece.ratio < 4.5)).toEqual([])
    // And they are the theme's dark colours, not the light ones under another name.
    expect(new Set(of(/\bmemory-text\b/).map(piece => `${piece.color} on ${piece.background}`))).toEqual(new Set(['228,230,234 on 26,30,38']))
  } finally {
    await request.put(`/api/projects/${project.id}/rules`, { headers: OWN, data: { rules: '' } })
  }
})

test('what an agent was given says how its source stands now, read again when its window opens', async ({ page }) => {
  await openFreshConversation(page)
  await noteThePort(page)
  await rail(page, 'Memory').click()
  await page.getByRole('button', { name: '● 1 fact waits for your word' }).click()
  await page.getByRole('region', { name: 'Waits for you' }).getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByRole('tabpanel', { name: /^Facts/ }).getByRole('article')).toContainText(FACT)

  await rail(page, 'Canvas').click()
  // The request and the Reviewer's task name the fact's subject, so the Reviewer is given it.
  await page.getByLabel('Message').fill('review the port of hello.py')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('The reviewer found no problems.')).toBeVisible({ timeout: 15_000 })

  let own = await openWindowOf(page, /^Reviewer$/)
  // (at the head of its steps)
  await openAgentFold(own, 'Every step as recorded')
  const given = own.getByRole('group', { name: 'Given from memory' })
  await expect(given).toContainText(FACT)
  await expect(given).toContainText('settings.txt:2-2 · now: source unchanged since noted')
  await own.getByRole('button', { name: 'Close agent window' }).click()

  // The file changes on disk. Nothing tells the page; it looks again when the window opens.
  writeFileSync(settings, '# settings\nThe service listens on port 9000.\n')
  own = await openWindowOf(page, /^Reviewer$/)
  await openAgentFold(own, 'Every step as recorded')
  await expect(own.getByRole('group', { name: 'Given from memory' })).toContainText(
    'settings.txt:2-2 · now: source changed since noted: check again',
  )
})
