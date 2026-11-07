// Slice 23 in the browser: a picture pasted into the message box, "Save these to the project too"
// ticked, is saved into docs/attachments/<date>-<name> as the message goes, said under the message;
// the box stays ticked for the project's next message.
import { rmdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { OWN, openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// A PNG of one pixel.
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

test('a pasted picture, ticked, is saved into docs/attachments/ and said under the message', async ({ page }: { page: Page }) => {
  const id = await openFreshConversation(page)
  // (At Auto edit the save is no card: what is looked at here is where it goes.)
  expect((await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'auto_edit' }, headers: OWN })).ok()).toBe(true)
  const box = page.getByLabel('Message')
  // A paste as the browser makes one, from its own data: the machine's clipboard is not touched.
  await box.evaluate((element, png) => {
    const data = new DataTransfer()
    data.items.add(new File([Uint8Array.from(atob(png), c => c.charCodeAt(0))], 'shot23.png', { type: 'image/png' }))
    element.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, PNG)
  await expect(page.getByRole('list', { name: 'Attached' }).getByRole('listitem')).toHaveCount(1)
  const save = page.getByLabel(/Save these to the project too/)
  await expect(save).not.toBeChecked()
  await save.check()
  await box.fill('keep this picture, 23')
  await page.getByRole('button', { name: 'Send' }).click()

  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText('Kept the picture.')).toBeVisible({ timeout: 20_000 })
  const said = chat.locator('.att-saved')
  await expect(said).toHaveText(/^saved to docs\/attachments\/\d{4}-\d{2}-\d{2}-shot23( \(\d+\))?\.png$/)
  const where = (await said.locator('.mono').textContent())!
  const snap = await (await page.request.get(`/api/conversations/${id}`)).json()
  const change = snap.file_changes.find((one: { path: string }) => one.path === where)
  expect(change.status).toBe('applied')
  const raw = await page.request.get(`/api/projects/${snap.conversation.project_id}/raw/${where.split('/').map(encodeURIComponent).join('/')}`)
  expect(Buffer.from(await raw.body()).equals(Buffer.from(PNG, 'base64'))).toBe(true)

  // Remembered for the project: the next file's box is ticked already.
  await page.locator('.att-menu-box input[type=file]').setInputFiles([{ name: 'note23.txt', mimeType: 'text/plain', buffer: Buffer.from('a note\n') }])
  await expect(save).toBeChecked()

  // (The shared e2e project is left as it was.)
  expect((await page.request.post(`/api/file-changes/${change.id}/revert`, { headers: OWN })).ok()).toBe(true)
  // (its folders too, where nothing else is in them: not recursive)
  for (const folder of ['docs/attachments', 'docs'])
    try {
      rmdirSync(path.join(PROJECT_DIR, folder))
    } catch {
      // not empty, or not there
    }
})
