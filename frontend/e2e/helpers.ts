// What several specs share. Not a spec itself: Playwright runs only *.spec.ts.
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { type APIRequestContext, expect, type Locator, type Page } from '@playwright/test'
import { APP_URL, PAGE_KEY, PROJECT_DIR, REPO_ROOT } from './paths.mjs'

/** What only the user may change is taken only from the app's own page, which says where it is from. */
export const OWN = { Origin: APP_URL }

/** The page as the link in KOLONİ's window opens it, with the key (slice 94). */
export const LINK = `/#key=${PAGE_KEY}`

/** The e2e's project, made one as the folder button makes it (slice 86a: there is no setup page); one that is already is answered with. */
export async function e2eProject(page: Page): Promise<string> {
  const made = await page.request.post('/api/projects', { data: { root_path: PROJECT_DIR }, headers: OWN })
  expect(made.ok()).toBe(true)
  return (await made.json()).id
}

/** K-bilgi: a knowledge of the e2e's project taken off its Knowledge page (and its roles), by its topic. */
export async function dropKnowledge(request: APIRequestContext, topic: string) {
  const made = await request.post('/api/projects', { data: { root_path: PROJECT_DIR }, headers: OWN })
  const pid: string = (await made.json()).id
  for (const one of (await (await request.get(`/api/projects/${pid}/knowledge`)).json()) as { id: string; project_id: string | null; knowledge: { topic: string } }[])
    if (one.project_id === pid && one.knowledge.topic === topic) expect((await request.delete(`/api/knowledge/${one.id}?project_id=${pid}`, { headers: OWN })).ok()).toBe(true)
}

/** The e2e project's settings, as Settings › This project saves them (tek-ev: a chat follows them, and is refused them). */
export async function setProject(page: Page, data: Record<string, unknown>) {
  const saved = await page.request.patch(`/api/projects/${await e2eProject(page)}`, { data, headers: OWN })
  expect(saved.ok()).toBe(true)
}

/** A project's sub-agent settings as a new one has them (`Project`, 0147). */
const SUB_AGENT_DEFAULTS = {
  spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6, spawn_max_parallel: 2, when_away: 'waits', away_minutes: 10,
  discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, room_min_tokens: 60000,
}

/**
 * A new conversation in the e2e's project, opened: KOLONİ opens on the chat with the latest activity, which this one is made.
 * `leadWrites`: the fake Lead writes files itself in most specs, so slice 48's default (the Lead hands code to sub-agents) is switched off unless a spec asks for it.
 */
export async function openFreshConversation(page: Page, { leadWrites = true } = {}) {
  const pid = await e2eProject(page)
  // Every chat follows its project's sub-agent settings (tek-ev): an earlier spec's are put back to the defaults.
  await setProject(page, { ...SUB_AGENT_DEFAULTS, lead_work: leadWrites ? 'itself' : 'delegates' })
  const made = await page.request.post('/api/conversations', { data: { project_id: pid }, headers: OWN })
  expect(made.ok()).toBe(true)
  const id: string = (await made.json()).id
  // Under load an earlier test's work (a turn ending) can touch its chat after this one was made, and the page
  // opens that one instead: so ours is touched again - any change but putting away is activity - and the page
  // opened again, a few times.
  for (let tries = 1; ; tries++) {
    // (before anything is sent; a project's chat is refused its project's settings, so a setting of its own)
    const patched = await page.request.patch(`/api/conversations/${id}`, { data: { plan_first: false }, headers: OWN })
    expect(patched.ok()).toBe(true)
    // The open chat is the one whose views are listed: a plain GET of a chat is no sign, the page reads every
    // other chat where something waits too (Ready for you) - and a spec once took one of those for its own.
    const opened = page.waitForResponse(r => r.request().method() === 'GET' && /^\/api\/conversations\/[0-9a-f]{32}\/views$/.test(new URL(r.url()).pathname))
    // (Away first: on the app already, the link differs only by its #key and would not load the page again.)
    await page.goto('about:blank')
    await page.goto(LINK)
    const first = await opened
    if (new URL(first.url()).pathname === `/api/conversations/${id}/views` && first.ok()) break
    expect(tries, `the page opened ${first.url()}, not ${id}`).toBeLessThan(3)
  }
  // (Its views listed: what an agent shows from now on is new, and opens Workspace by itself - slice 42c.)
  await page.getByLabel('Message').waitFor()
  return id
}

/** Wait until the canvas has finished fitting itself to the turn. */
export async function settled(page: Page) {
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

export async function say(page: Page, message: string, answer: string | RegExp) {
  await page.getByLabel('Message').fill(message)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText(answer).last()).toBeVisible({ timeout: 20_000 })
}

/**
 * Opens More under the message box, where it is not open (slice 38b): the
 * sub-agents, what runs without asking and Work together are in it.
 */
/** Settings › This project, opened from ⚙ on the rail, at a section (tek-ev); ⚙ again closes it. */
export async function projectSettings(page: Page, section?: RegExp) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  if (section) await settings.getByRole('button', { name: section }).click()
  return settings
}

/** Settings › The app › Voice (this browser's), opened from ⚙ on the rail; ⚙ again closes it. */
export async function voiceSettings(page: Page) {
  await appSettings(page, 'Voice')
  return page.getByRole('region', { name: 'Voice' })
}

/** Settings › The app at a section, opened from ⚙ on the rail; what it shows. */
export async function appSettings(page: Page, section: 'Agents' | 'Voice' | 'Your data') {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const levels = page.getByRole('navigation', { name: 'Settings levels' })
  await levels.getByRole('button', { name: 'The app' }).click()
  await levels.getByRole('button', { name: section, exact: true }).click()
  // (The section shown: the others are hidden beside it.)
  return page.locator('.settings-panel:not([hidden]) .role-editor > :not([hidden])')
}

/** A section of Settings › This project saved, and Settings closed: back on the canvas. */
export async function saveSettings(page: Page) {
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: 'Save' }).click()
  await expect(settings.getByRole('status')).toHaveText('Saved')
  await page.getByRole('button', { name: 'Close settings' }).click()
  await expect(settings).toHaveCount(0)
}

export async function more(page: Page) {
  const button = page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'More', exact: true })
  if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click()
}

/** ⚙ Chat beside the level: this chat's own settings, opened where they are not open. */
export async function chatSheet(page: Page) {
  const button = page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'This chat’s settings' })
  if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click()
  return page.getByRole('dialog', { name: 'This chat' })
}

/** Recent, opened from its button in the top bar where it is not open (slice 38b; 107). */
export async function openTurns(page: Page) {
  const button = page.getByRole('button', { name: /^Recent/ })
  if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click()
  return page.getByRole('complementary', { name: 'Recent' })
}

/**
 * The part of the canvas the chat and the canvas's buttons (bottom right, K-66-kalan) do not cover, on the
 * screen: the largest of what is beside the chat left of the buttons, beside it above them, and above the
 * chat (slice 38b). The canvas fits and centres its turn there.
 */
export async function freeOfChat(page: Page) {
  const [stage, chat, buttons] = await Promise.all(['.canvas-flow', '.chat', '.react-flow__controls'].map(async s => (await page.locator(s).boundingBox())!))
  const right = chat.x + chat.width
  const pieces = [
    { x: right, y: stage.y, width: buttons.x - right, height: stage.height },
    { x: right, y: stage.y, width: stage.x + stage.width - right, height: buttons.y - stage.y },
    { x: stage.x, y: stage.y, width: stage.width, height: Math.min(chat.y, buttons.y) - stage.y },
  ]
  return pieces.reduce((best, piece) => (piece.width * piece.height > best.width * best.height ? piece : best))
}

export const rail = (page: Page, name: 'Memory' | 'Canvas' | 'Chats' | 'Triggers' | 'Models' | 'Tools' | 'Usage' | 'Ready' | 'Board' | 'To-do') =>
  page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name, exact: true })

/** On the Agents page (slice 63b): a role's row in the library, or the Lead's strip. */
export const roleRow = (page: Page, name: string) =>
  name === 'Lead' ? page.getByRole('button', { name: 'Open the Lead' }) : page.getByRole('complementary', { name: 'Roles' }).getByRole('button', { name: new RegExp(`^${name}`) }).first()

/**
 * On the Agents page (slice 81b): a role opened, then one part of its form - its model, reasoning
 * and limits ("Edit model" on its Overview), or the form behind its Instructions or Tools tab.
 */
export async function editRole(page: Page, name: string, part: 'tiers' | 'Instructions' | 'Tools') {
  await roleRow(page, name).click()
  const panel = page.getByRole('complementary', { name: `Role ${name}` })
  if (part === 'tiers') return panel.getByRole('button', { name: 'Edit model' }).click()
  await panel.getByRole('tab', { name: part }).click()
  // (Slice 81d: its tools are the tab's own tiles; K-skill-uyum: its skills too.)
  if (part === 'Tools') return
  await panel.getByRole('button', { name: 'Edit', exact: true }).click()
}

/**
 * A long note shows its first sentence; the rest is folded under "More" (slice 31). Opens
 * the fold that holds this text, as a reader would to read it.
 */
export async function unfold(root: Page | Locator, text: string | RegExp) {
  await root.locator('details.more', { hasText: text }).locator('summary').click()
}

/** Opens a section of the Usage page that is folded under its heading (slice 60a), as a reader would. */
export async function openFold(page: Page, name: string) {
  await page.getByRole('region', { name }).locator('details.usage-fold > summary').click()
}

/** Screenshots for a person to look at after a run: under runtime/, which git ignores and no run clears. */
const SHOTS = path.join(REPO_ROOT, 'runtime', 'shots')

export async function shot(target: Page | Locator, name: string) {
  mkdirSync(SHOTS, { recursive: true })
  await target.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

/**
 * Every piece of text inside `root`, with its colour, the background it is drawn on and
 * the contrast between the two by the WCAG 2 formula: relative luminance
 * L = 0.2126 R + 0.7152 G + 0.0722 B over linearised sRGB, ratio (L1 + 0.05) / (L2 + 0.05).
 * Colours are the browser's resolved ones; a see-through layer is laid over what is under it.
 * (Run in the page: it may use nothing from outside itself.)
 */
export function contrasts(root: Element) {
  type Rgba = [number, number, number, number]
  const parse = (value: string): Rgba => {
    const numbers = (value.match(/-?\d*\.?\d+(e-?\d+)?%?/g) ?? []).map(n => (n.endsWith('%') ? Number(n.slice(0, -1)) / 100 : Number(n)))
    // "color(srgb r g b / a)" is how the browser resolves color-mix(): channels from 0 to 1.
    if (value.startsWith('color(srgb')) return [numbers[0] * 255, numbers[1] * 255, numbers[2] * 255, numbers[3] ?? 1]
    if (value.startsWith('rgb')) return [numbers[0], numbers[1], numbers[2], numbers[3] ?? 1]
    throw new Error(`a colour this test cannot read: ${value}`)
  }
  const over = (top: Rgba, under: Rgba): Rgba => [
    top[0] * top[3] + under[0] * (1 - top[3]),
    top[1] * top[3] + under[1] * (1 - top[3]),
    top[2] * top[3] + under[2] * (1 - top[3]),
    1,
  ]
  const luminance = ([r, g, b]: Rgba) => {
    const linear = (channel: number) => {
      const c = channel / 255
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
  }
  const backgroundOf = (element: Element): Rgba => {
    const layers: Rgba[] = []
    for (let at: Element | null = element; at; at = at.parentElement) layers.push(parse(getComputedStyle(at).backgroundColor))
    // From the page outwards in: the canvas is white where nothing at all is painted.
    return layers.reverse().reduce<Rgba>((under, layer) => over(layer, under), [255, 255, 255, 1])
  }
  const found: { text: string; cls: string; color: string; background: string; ratio: number }[] = []
  for (const element of [root, ...root.querySelectorAll('*')]) {
    const text = Array.from(element.childNodes).filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent ?? '').join('').trim()
    // A control that is switched off is not text to be read (WCAG 1.4.3 leaves it out).
    if (!text || element.closest(':disabled') || !(element as HTMLElement).offsetParent) continue
    const background = backgroundOf(element)
    const color = over(parse(getComputedStyle(element).color), background)
    const [light, dark] = [luminance(color), luminance(background)].sort((a, b) => b - a)
    found.push({
      text: text.slice(0, 40),
      cls: `${element.tagName.toLowerCase()}.${element.className}`,
      color: color.slice(0, 3).map(Math.round).join(','),
      background: background.slice(0, 3).map(Math.round).join(','),
      ratio: Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100,
    })
  }
  return found
}

/**
 * The colours a stylesheet names itself, apart from the theme's variables: none, for a
 * page that is to be right in both themes. Returns what it found.
 */
export function ownColours(css: string): string[] {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const fixed = plain.match(/#[0-9a-f]{3,8}\b|\b(rgba?|hsla?|oklch|oklab|color)\([^)]*\)/gi) ?? []
  const values = Array.from(plain.matchAll(/(?:^|[\s;{])(?:color|background(?:-color)?|border(?:-[a-z]+)?|box-shadow|outline)\s*:\s*([^;}]+)/g)).map(m => m[1])
  const named = values.filter(value => /\b(white|black|gr[ae]y|red|green|blue|yellow|orange|purple|silver)\b/.test(value.replace(/var\(--[\w-]+\)/g, '')))
  return [...fixed, ...named]
}

/** The agent the side panel shows, in its own window (Open window pressed): its whole story and Details are there. */
export async function windowFromPanel(page: Page): Promise<Locator> {
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  return page.getByRole('region', { name: 'Agent window' })
}

/** One of an agent's folds, in the panel or its window, by the words its own line starts with (not a fold inside it). */
export const agentFold = (root: Locator, name: string) => root.locator('details.agent-fold > summary', { hasText: name }).locator('..')

/** That fold, opened if it is not: what is in it is seen. One inside the window's Details (its raw steps) opens Details first. */
export async function openAgentFold(root: Locator, name: string) {
  if (name !== 'Details' && (await agentFold(root, name).count()) === 0) await openAgentFold(root, 'Details')
  const it = agentFold(root, name)
  if (!(await it.evaluate(d => (d as HTMLDetailsElement).open))) await it.locator('xpath=./summary').click()
  await expect(it).toHaveAttribute('open', '')
  return it
}
