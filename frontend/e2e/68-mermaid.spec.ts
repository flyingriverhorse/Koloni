// Slice 68 in the browser, with the real mermaid: a ```mermaid block in the chat and in the Workspace's
// .md preview is drawn as a diagram - an image named for its kind or its title, its source a press
// away - in both themes, drawn anew when the theme changes; one mermaid cannot draw stays code with
// mermaid's first error line under it; a diagram's own settings change nothing the app set, and no
// picture it names (in a label, a shape or its CSS) is drawn or fetched.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'
import { MODEL_URL } from './paths.mjs'

// (tall enough for the open chat to show the whole answer in a shot)
test.use({ viewport: { width: 1440, height: 1400 } })

const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const themeButton = (page: Page) => page.getByRole('button', { name: /^Theme: switch to (dark|light)$/ })

/**
 * Every piece of text in a drawn diagram against what it is drawn on: the filled shape of the group
 * it is in, else the page behind the drawing. (Run in the page: it may use nothing from outside itself.)
 */
function svgContrasts(svg: Element) {
  const rgb = (value: string) => (value.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map(Number)
  const luminance = (channels: number[]) => {
    const [r, g, b] = channels.map(c => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const filled = (shape: Element) => {
    const fill = getComputedStyle(shape).fill
    return fill.startsWith('rgb') && !/, 0\)$/.test(fill) ? fill : null
  }
  let page: Element | null = svg
  while (page && !/^rgb\(/.test(getComputedStyle(page).backgroundColor)) page = page.parentElement
  const behind = page ? getComputedStyle(page).backgroundColor : 'rgb(255, 255, 255)'
  // (the piece that holds the words: a <tspan> has a fill of its own, the <text> around it may not show)
  return Array.from(svg.querySelectorAll('text, tspan'))
    .filter(text => Array.from(text.childNodes).some(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()))
    .map(text => {
      let under: string | null = null
      for (let group = text.closest('g'); group && !under; group = group.parentElement?.closest('g') ?? null)
        for (const shape of group.querySelectorAll(':scope > rect, :scope > path, :scope > polygon, :scope > circle, :scope > ellipse')) under ??= filled(shape)
      const [a, b] = [luminance(rgb(getComputedStyle(text).fill)), luminance(rgb(under ?? behind))].sort((x, y) => y - x)
      return { text: text.textContent!.trim().slice(0, 30), color: getComputedStyle(text).fill, under: under ?? behind, ratio: (a + 0.05) / (b + 0.05) }
    })
}

/** The words and the drawing in it, all at 4.5 or more. */
async function readable(root: Locator, drawing: Locator) {
  const words = await root.evaluate(contrasts)
  expect(words.filter(piece => piece.ratio < 4.5)).toEqual([])
  const drawn = await drawing.evaluate(svgContrasts)
  expect(drawn.length).toBeGreaterThan(0)
  expect(drawn.filter(piece => piece.ratio < 4.5)).toEqual([])
}

const themeIs = (page: Page, dark: boolean) => expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(dark)

test('a diagram in an answer is drawn, a broken one stays code with its error, nothing it names is fetched, in both themes', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'light'))
  // (what the page's policy stops never leaves it: the browser names it and turns it down itself)
  const [asked, stopped]: string[][] = [[], []]
  page.on('request', request => request.url().includes('pixel.png') && asked.push(request.url()))
  page.on('requestfailed', request => request.failure()?.errorText === 'csp' && stopped.push(request.url()))
  const elk: string[] = []
  page.on('request', request => /elk/i.test(new URL(request.url()).pathname) && elk.push(request.url()))
  await openFreshConversation(page)
  const chat = chatOf(page)
  await page.getByLabel('Message').fill('draw me a diagram')
  await page.getByRole('button', { name: 'Send' }).click()

  const drawing = chat.getByRole('img', { name: 'Diagram: flowchart' })
  await expect(drawing).toBeVisible({ timeout: 20_000 })
  expect(await drawing.evaluate(el => el.tagName.toLowerCase())).toBe('svg')
  await expect(drawing).toContainText('Work')
  // The broken one: its code as it was, and mermaid's first error line.
  await expect(chat.getByText(/^Could not draw this diagram: Parse error on line \d+:$/)).toBeVisible()
  await expect(chat.locator('pre code', { hasText: 'A -->' })).toBeVisible()
  // The picture in a shape is not fetched (the page's own policy): that diagram stays code.
  await expect(chat.getByText(/^Could not draw this diagram: /)).toHaveCount(2)
  await expect(chat.locator('pre code', { hasText: 'pixel.png?shape' })).toBeVisible()
  await expect(chat.locator('.md-diagram [role="img"]')).toHaveCount(3)
  // Asked for ELK, which is not shipped: laid out with dagre, and nothing of ELK is asked for.
  await expect(chat.getByRole('img', { name: 'Laid out anyway' })).toContainText('Second')
  // A diagram's own settings change nothing the app set: no HTML in labels, the app's theme, no CSS of its own.
  const lucky = chat.getByRole('img', { name: 'Trying its luck' })
  await expect(lucky).toBeVisible()
  await expect(lucky.locator('foreignObject, b')).toHaveCount(0)
  const fill = (svg: Locator) => svg.locator('g.node rect, g.node path').first().evaluate(el => getComputedStyle(el).fill)
  expect(await fill(lucky)).toBe(await fill(drawing))
  // An image in a label, in an image shape or in the diagram's CSS is neither an element nor fetched.
  await expect(chat.locator('img')).toHaveCount(0)
  await page.waitForLoadState('networkidle')
  expect(stopped).toEqual([`${MODEL_URL}/pixel.png?shape`])
  expect(asked).toEqual(stopped)
  expect(elk).toEqual([])

  // Its source is a press away.
  const diagram = chat.locator('.md-diagram', { has: page.getByRole('img', { name: 'Diagram: flowchart' }) })
  await diagram.getByRole('button', { name: 'Show source' }).click()
  await expect(diagram.locator('pre code')).toContainText('ask[Ask] --> work[Work]')
  await diagram.getByRole('button', { name: 'Hide source' }).click()
  await expect(diagram.locator('pre')).toHaveCount(0)

  const message = chat.locator('.msg-assistant', { has: page.getByRole('img', { name: 'Diagram: flowchart' }) })
  await readable(message, drawing)
  if (process.env.KOLONI_SHOTS) await shot(message, '68-chat-light')
  const lightFill = await fill(drawing)

  // The app turns dark: the diagram is drawn anew in mermaid's dark theme.
  await themeButton(page).click()
  await themeIs(page, true)
  await expect.poll(() => fill(drawing)).not.toBe(lightFill)
  expect(await fill(lucky)).toBe(await fill(drawing))
  await readable(message, drawing)
  if (process.env.KOLONI_SHOTS) await shot(message, '68-chat-dark')
})

test('a .md file with a diagram is drawn in the Workspace preview, in both themes', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'dark'))
  const id = await openFreshConversation(page)
  try {
    await page.getByLabel('Message').fill('write the diagram note')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chatOf(page).getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 20_000 })
    const panel = page.getByRole('region', { name: 'Workspace' })
    await expect(panel.getByRole('tab', { name: 'diagram68.md' })).toHaveAttribute('aria-selected', 'true')
    await panel.getByRole('button', { name: 'Preview' }).click()

    // Named by its own title (accTitle).
    const drawing = panel.getByRole('img', { name: 'Sign-in steps' })
    await expect(drawing).toBeVisible({ timeout: 15_000 })
    await expect(panel.getByRole('heading', { name: 'Signing in' })).toBeVisible()
    const body = panel.locator('.view-md')
    await readable(body, drawing)
    if (process.env.KOLONI_SHOTS) await shot(panel, '68-preview-dark')

    await themeButton(page).click()
    await themeIs(page, false)
    await expect(drawing).toBeVisible()
    await readable(body, drawing)
    if (process.env.KOLONI_SHOTS) await shot(panel, '68-preview-light')
  } finally {
    // Left as it was found: the note still waiting is turned down.
    const conv = await (await page.request.get(`/api/conversations/${id}`)).json()
    for (const change of conv.file_changes ?? [])
      if (change.status === 'proposed') await page.request.post(`/api/file-changes/${change.id}/reject`, { headers: OWN })
  }
})
