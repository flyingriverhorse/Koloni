import { expect, test } from './fixtures'
import { openFreshConversation } from './helpers'

// B-337 (live): "Close without saving what you changed?" was the browser's own confirm, which
// locked the tab and a browser an agent drives. Now it is KOLONİ's, inside the panel.
test('closing the model picker with a change asks in KOLONİ, never in a native dialog', async ({ page }) => {
  const native: string[] = []
  page.on('dialog', dialog => {
    native.push(dialog.message())
    void dialog.dismiss()
  })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: /^Model: / }).click()
  const form = chat.getByRole('form', { name: 'Model for this conversation' })
  await form.getByLabel('Provider').selectOption({ label: 'Local' })
  await page.getByRole('button', { name: 'Canvas', exact: true }).click()

  const asked = page.getByRole('alertdialog', { name: 'Close without saving what you changed?' })
  await expect(asked).toBeVisible()
  await expect(asked.getByRole('button', { name: 'Close without saving' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(asked).toBeHidden()
  await expect(form.getByLabel('Provider')).toHaveValue(/.+/)

  await page.keyboard.press('Escape')
  await asked.getByRole('button', { name: 'Close without saving' }).click()
  await expect(form).toBeHidden()
  expect(native).toEqual([])
})
