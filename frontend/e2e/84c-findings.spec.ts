import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, say, settled, shot } from './helpers'

// Slice 84c: findings go to the right role. The fake Reviewer ends its report with two findings, one for the
// Coder and one for the UI designer; the Lead hands the Coder its one (findings_from). The Reviewer's node says
// what it found by role, a dashed line in the warn colour goes from it to the Coder with how many it carried,
// and the legend says what that line is. Nothing leaves the machine: the fake model answers.
test.use({ viewport: { width: 1440, height: 900 } })

/** The WCAG 2 contrast of two opaque "rgb(r, g, b)" colours (an SVG label's fill, which `contrasts` does not read). */
function ratio(one: string, other: string) {
  const luminance = (rgb: string) => {
    const [r, g, b] = rgb.match(/\d+/g)!.map(n => Number(n) / 255).map(c => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [light, dark] = [luminance(one), luminance(other)].sort((a, b) => b - a)
  return (light + 0.05) / (dark + 0.05)
}

for (const theme of ['light', 'dark'] as const) {
  test(`a review's findings are handed on to the role they name, and the canvas shows it (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    // The Coder is opened without asking, so that nothing in this turn waits for the user.
    await page.getByLabel('Permission level').selectOption('auto_edit')
    await expect(page.getByLabel('Permission level')).toHaveValue('auto_edit')

    await say(page, 'review and hand on the greeting', 'The Coder fixed what the review found.')
    const agents = page.locator('.react-flow__node-agent')
    const box = (name: string) => agents.filter({ has: page.locator('.node-title', { hasText: new RegExp(`^${name}$`) }) })
    // Done, its state line says what it found, by role (each finding is in the side panel - the user's, 5 Nov).
    const found = box('Reviewer').locator('.node-line')
    await expect(found).toHaveText('Done · 2 findings → Coder, UI designer')
    await expect(found).toHaveAttribute('title', 'Done · 2 findings → Coder, UI designer')
    // (the Coder's report has no Findings section: its node says nothing of findings)
    await expect(box('Coder').locator('.node-line')).toHaveText('Done ✓')
    expect((await found.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    const line = page.locator('.react-flow__edge.edge-findings')
    await expect(line).toHaveCount(1)
    await expect(line.locator('.react-flow__edge-path')).toHaveAttribute('style', /stroke: var\(--warn\).*stroke-dasharray: 8,? 3/)
    // a short line from under the Reviewer's box to the top of the Coder's, not round their sides
    await settled(page)
    const [from, to, path] = await Promise.all([box('Reviewer'), box('Coder'), line.locator('.react-flow__edge-path')].map(l => l.boundingBox()))
    expect(path!.y).toBeGreaterThanOrEqual(from!.y + from!.height - 2)
    expect(path!.y + path!.height).toBeLessThanOrEqual(to!.y + 2)
    await expect(page.locator('.react-flow__edge-text', { hasText: /^1 finding$/ })).toBeVisible()
    // its label stands on the canvas's own background, in the line's colour, and reads at 4.5 or more
    const canvas = await page.locator('.react-flow').evaluate(element => getComputedStyle(element).backgroundColor)
    expect(await line.locator('.react-flow__edge-textbg').evaluate(element => getComputedStyle(element).fill)).toBe(canvas)
    const label = await line.locator('.react-flow__edge-text').evaluate(element => getComputedStyle(element).fill)
    expect(ratio(label, canvas)).toBeGreaterThanOrEqual(4.5)
    // beside the line, not over it (slice 84d): the words and their ground both stand right of it
    const [words, ground] = await Promise.all([line.locator('.react-flow__edge-text'), line.locator('.react-flow__edge-textbg')].map(l => l.boundingBox()))
    expect(words!.x).toBeGreaterThan(path!.x + path!.width)
    expect(ground!.x).toBeGreaterThanOrEqual(path!.x + path!.width)
    // and the line is longer than its label is tall: seen, between boxes stood further apart
    expect(path!.height).toBeGreaterThan(2 * words!.height)
    await settled(page)
    await shot(page, `84c-findings-${theme}`)

    await page.getByRole('button', { name: 'Canvas legend' }).click()
    const legend = page.getByRole('dialog', { name: 'Canvas legend' })
    const row = legend.getByRole('listitem').filter({ hasText: /^Findings handed on/ })
    await expect(row).toHaveCount(1)
    expect((await row.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}
