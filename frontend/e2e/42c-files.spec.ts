// Slice 42c in the browser: one Workspace window, as VS Code has it. The project's tree under its
// folder's name, read a folder at a time and worked from the keyboard; a changed file once, marked
// M / A / D, with only its latest change as a coloured diff (side by side or in one column,
// remembered; one column when narrow); a page previewed by slice 39's rules or read as code; any
// other file read as code. One Workspace button - its number what waits for you, as the Board counts it.
// "View changes" opens it at the file. Every text at 4.5 in both themes.
import { existsSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const ROOT = path.basename(PROJECT_DIR)
const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const filesOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })
const treeOf = (page: Page) => filesOf(page).getByRole('tree', { name: 'Files' })
const workspaceButton = (page: Page) => page.getByRole('button', { name: /^Workspace/ })

async function check(root: Locator, least: number) {
  // (Read again till the least is drawn: the window draws its pieces in steps, and once too few were read.)
  await expect
    .poll(async () => {
      const pieces = await root.evaluate(contrasts)
      return pieces.length < least ? `only ${pieces.length} of ${least} pieces drawn` : pieces.filter(piece => piece.ratio < 4.5)
    })
    .toEqual([])
}

async function rejectWaiting(page: Page, id: string) {
  if (!id) return
  const conv = await (await page.request.get(`/api/conversations/${id}`)).json()
  for (const change of conv.file_changes ?? [])
    if (change.status === 'proposed') await page.request.post(`/api/file-changes/${change.id}/reject`, { headers: OWN })
}

// The page the changes below change: as spec 39 leaves it, or one of its own when this spec runs alone.
test.beforeAll(() => {
  const page = path.join(PROJECT_DIR, 'view39.html')
  if (!existsSync(page)) writeFileSync(page, '<!doctype html>\n<h1>A page before the agent</h1>\n<p id="said">not run</p>\n')
})

/** In the chat open, a change to a page waits for the user: Workspace opens by itself, on it. */
async function aPageWaits(page: Page) {
  // (the version spec 39 leaves unwritten - or the one written above: a change whichever ran before)
  await page.getByLabel('Message').fill('change the view page')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chatOf(page).getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 20_000 })
  await expect(filesOf(page)).toBeVisible()
}

test('a change that waits opens Workspace on its file: under the project folder’s name, once, M and a dot; its latest diff coloured, side by side or in one column - remembered, one column when narrow', async ({ page }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page)
  try {
    await aPageWaits(page)
    const files = filesOf(page)
    const root = treeOf(page).getByRole('treeitem', { name: `${ROOT} changed` })
    await expect(root).toHaveAttribute('aria-level', '1')
    await expect(root).toHaveAttribute('aria-expanded', 'true')
    // no section heading above it: nothing is served
    await expect(treeOf(page).getByRole('treeitem', { name: /^(Artifacts|Images|Previews)$/ })).toHaveCount(0)
    const file = treeOf(page).getByRole('treeitem', { name: 'view39.html modified, Waits for you' })
    await expect(file).toHaveCount(1)
    await expect(file).toHaveAttribute('aria-selected', 'true')
    await expect(file).toHaveAttribute('title', /^view39\.html · Waits for you · by Lead · \d/)
    await expect(file.locator('.tree-mark-warn')).toHaveText('M')
    await expect(file.locator('.tree-wait')).toBeVisible()
    await expect(files.getByText('1 file waits')).toBeVisible()
    // coloured as HTML; an added line said in words too
    await expect(files.locator('.changes-body .hljs-tag').first()).toBeVisible()
    await expect(files.locator('.diff-add .visually-hidden').first()).toHaveText(/^added\s*$/)
    await expect(files.locator('.diff-add .diff-sign').first()).toHaveText('+')
    // expanded, a diff side by side at first; in one column once chosen, and still after a reload
    await files.getByRole('button', { name: 'Expand workspace' }).click()
    const button = files.getByRole('button', { name: 'Side by side' })
    await expect(button).toHaveAttribute('aria-pressed', 'true')
    await expect(files.locator('.diff-split')).toBeVisible()
    await button.click()
    await expect(files.locator('.diff-split')).toHaveCount(0)
    await page.reload()
    // (its button opens it on what waits)
    await workspaceButton(page).click({ timeout: 15_000 })
    await filesOf(page).getByRole('button', { name: 'Expand workspace' }).click()
    await expect(filesOf(page).getByRole('button', { name: 'Side by side' })).toHaveAttribute('aria-pressed', 'false', { timeout: 15_000 })
    await expect(filesOf(page).locator('.diff-split')).toHaveCount(0)
    await filesOf(page).getByRole('button', { name: 'Side by side' }).click()
    await expect(filesOf(page).locator('.diff-split')).toBeVisible()
    // a narrow window: one column, whatever was chosen
    await page.setViewportSize({ width: 700, height: 900 })
    await expect(filesOf(page).locator('.diff-split')).toHaveCount(0)
    await expect(filesOf(page).getByRole('button', { name: 'Side by side' })).toBeDisabled()
  } finally {
    await rejectWaiting(page, id)
  }
})

test('on a 1280-1366 px screen a diff goes side by side in the window as it opens, once the files are hidden (K-42a)', async ({ page }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page)
  try {
    await page.setViewportSize({ width: 1280, height: 720 })
    await aPageWaits(page)
    const files = filesOf(page)
    const button = files.getByRole('button', { name: 'Side by side' })
    // beside the files it is one column, and the button says how to have two
    await expect(button).toBeDisabled()
    await expect(button).toHaveAttribute('title', 'Too narrow for two columns: hide the files, or expand the window')
    await files.getByRole('button', { name: 'Hide files' }).click()
    for (const size of [{ width: 1280, height: 720 }, { width: 1366, height: 768 }]) {
      await page.setViewportSize(size)
      await expect(button).toBeEnabled()
      if ((await button.getAttribute('aria-pressed')) === 'false') await button.click()
      await expect(files.locator('.diff-split')).toBeVisible()
      if (process.env.KOLONI_SHOTS) await shot(page, `42a-side-by-side-${size.width}`)
    }
  } finally {
    await rejectWaiting(page, id)
  }
})

test('the Workspace button’s number is what waits for you as the Board counts it; approved, "View changes" opens Workspace at the file', async ({ page }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page)
  try {
    await aPageWaits(page)
    await expect(workspaceButton(page)).toHaveAccessibleName('Workspace 1 waiting', { timeout: 15_000 })
    // (a small one at the open chat's foot, at the end of the model's line; none in its header nor the top bar - slice 42d)
    await expect(chatOf(page).locator('.composer-line').getByRole('button', { name: /^Workspace/ })).toHaveCount(1)
    await expect(chatOf(page).locator('.chat-top').getByRole('button', { name: /^Workspace/ })).toHaveCount(0)
    await expect(page.getByRole('banner').getByRole('button', { name: /^Workspace/ })).toHaveCount(0)
    await chatOf(page).getByRole('button', { name: 'Approve' }).click()
    await expect(chatOf(page).getByText('The page is written.')).toBeVisible({ timeout: 20_000 })
    await expect(workspaceButton(page)).toHaveAccessibleName('Workspace 0 waiting', { timeout: 15_000 })
    if (await filesOf(page).isVisible()) await filesOf(page).getByRole('button', { name: 'Close workspace' }).click()
    // (under the answer's work line, in its details: slice 107)
    await chatOf(page).getByRole('button', { name: 'details ▸' }).last().click()
    await chatOf(page).getByRole('button', { name: 'View changes' }).last().click()
    await expect(filesOf(page).getByRole('tab', { name: 'view39.html' })).toHaveAttribute('aria-selected', 'true')
    await expect(treeOf(page).getByRole('treeitem', { name: 'view39.html modified, Applied' })).toHaveAttribute('aria-selected', 'true')
    // (taken back: the page is as the next test finds it)
    await filesOf(page).getByRole('button', { name: 'Revert' }).click()
    await expect(filesOf(page).locator('.change-actions').getByText('Reverted', { exact: true })).toBeVisible()
  } finally {
    await rejectWaiting(page, id)
  }
})

const PAGE = path.join(PROJECT_DIR, 'page42c.html')
const SECRET = path.join(PROJECT_DIR, '.env')
test.describe('a file of the project that did not change', () => {
  test.beforeEach(() => {
    writeFileSync(PAGE, '<h1>Plain page</h1>\n<p id="said">not run</p>\n<script>document.getElementById("said").textContent = "ran"</script>\n')
    writeFileSync(SECRET, 'TOKEN=s3cr3t\n')
  })
  test.afterEach(() => [PAGE, SECRET].forEach(file => rmSync(file, { force: true })))

  test('a page is previewed - its script run only once asked - or read as code; any other file is code; a secret is not in the tree; the tree from the keyboard', async ({ page }) => {
    test.setTimeout(60_000)
    await openFreshConversation(page)
    await workspaceButton(page).click()
    const files = filesOf(page)
    const tree = treeOf(page)
    const pageItem = tree.getByRole('treeitem', { name: 'page42c.html' })
    await expect(pageItem).toBeVisible({ timeout: 10_000 })
    await expect(tree.getByRole('treeitem', { name: '.env' })).toHaveCount(0)
    await pageItem.click()
    const frame = page.frameLocator('.view-panel iframe')
    await expect(frame.locator('h1')).toHaveText('Plain page')
    await expect(files.locator('iframe')).toHaveAttribute('sandbox', '')
    await expect(frame.locator('#said')).toHaveText('not run')
    await files.getByRole('group', { name: 'Run its script?' }).getByRole('button', { name: 'Run once' }).click()
    await expect(frame.locator('#said')).toHaveText('ran')
    await files.getByRole('button', { name: 'Code' }).click()
    await expect(files.locator('iframe')).toHaveCount(0)
    await expect(files.locator('.changes-body .hljs-tag').first()).toBeVisible()
    await expect(files.locator('.changes-body .diff-no').first()).toHaveText('1')
    await tree.getByRole('treeitem', { name: 'hello.py' }).click()
    await expect(files.locator('.changes-body .diff-text').first()).toContainText('print')
    await expect(files.getByRole('tablist', { name: 'Open files' }).getByRole('tab')).toHaveText(['page42c.html', 'hello.py'])
    if (process.env.KOLONI_SHOTS) await shot(page, '42c-code')

    // the keyboard: Home to the root, left closes it, right opens it, End and Enter open the last file; Esc closes, back on its button
    await tree.getByRole('treeitem', { name: 'hello.py' }).focus()
    await page.keyboard.press('Home')
    const root = tree.getByRole('treeitem', { name: ROOT, exact: true })
    await expect(root).toBeFocused()
    await page.keyboard.press('ArrowLeft')
    await expect(root).toHaveAttribute('aria-expanded', 'false')
    await expect(tree.getByRole('treeitem', { name: 'hello.py' })).toHaveCount(0)
    await page.keyboard.press('ArrowRight')
    await expect(root).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('ArrowDown')
    await expect(tree.getByRole('treeitem').nth(1)).toBeFocused()
    await page.keyboard.press('End')
    await page.keyboard.press('Enter')
    await expect(files.getByRole('tablist', { name: 'Open files' }).getByRole('tab')).toHaveCount(3)
    await page.keyboard.press('Escape')
    await expect(files).toBeHidden()
    // (back on the button that opened it: the chat's own, at its foot)
    await expect(workspaceButton(page)).toBeFocused()
    // a narrow window: the files hidden at first, shown by a button
    await page.setViewportSize({ width: 700, height: 900 })
    await workspaceButton(page).click()
    await expect(files.getByRole('tree')).toHaveCount(0)
    await files.getByRole('button', { name: 'Show files' }).click()
    await expect(files.getByRole('tree', { name: 'Files' })).toBeVisible()
  })
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme every text of the Workspace window, its tree, the coloured diff and its button stands out from what it is on (contrast 4.5 or more)`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    try {
      await aPageWaits(page)
      const files = filesOf(page)
      await expect(files.locator('.hljs-tag').first()).toBeVisible()
      await expect(workspaceButton(page)).toHaveAccessibleName(/^Workspace \d+ waiting/, { timeout: 15_000 })
      await check(workspaceButton(page), 1)
      await check(treeOf(page), 3)
      await check(files.locator('.files-waiting'), 2)
      await check(files.locator('.changes-body'), 10)
      if (process.env.KOLONI_SHOTS) await shot(page, `42c-files-${theme}`)
      await files.getByRole('button', { name: 'Expand workspace' }).click()
      await check(files.locator('.changes-body'), 10)
      if (process.env.KOLONI_SHOTS) await shot(files, `42c-diff-side-by-side-${theme}`)
      await files.getByRole('button', { name: 'Preview' }).click()
      // (the file's line, and K-39's ask to run its script: Run once, Always run in this chat, Don't run)
      await check(files.locator('.view-where').first(), 3)
      await check(files.getByRole('group', { name: 'Run its script?' }), 4)
      if (process.env.KOLONI_SHOTS) await shot(files, `42c-preview-${theme}`)
    } finally {
      await rejectWaiting(page, id)
    }
  })
