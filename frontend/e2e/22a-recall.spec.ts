import { expect, test } from './fixtures'
import { openFreshConversation, rail } from './helpers'

test('what was said in an earlier turn is found from the Memory page, with whose words it is', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('Answer only: The ZEPPELIN hangar is in Kayseri.')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The ZEPPELIN hangar is in Kayseri.', { exact: true })).toBeVisible({ timeout: 15_000 })

  await rail(page, 'Memory').click()
  const region = page.getByRole('region', { name: 'Search', exact: true })
  // spelled otherwise: capitals and letters with marks do not hide a word
  await region.getByLabel('Search everything this project remembers').fill('zeppelin KAYSERİ')
  await region.getByRole('button', { name: 'Search deeper' }).click()
  const said = region.getByRole('list', { name: 'In earlier messages' }).getByRole('listitem')
  await expect(said).toHaveCount(2)
  await expect(said.filter({ hasText: /^“Answer only: The ZEPPELIN hangar is in Kayseri\.”/ })).toContainText('You ·')
  await expect(said.filter({ hasText: /^“The ZEPPELIN hangar is in Kayseri\.”/ })).toContainText('Lead ·')
  await expect(region.getByText('Nothing on record speaks to “zeppelin KAYSERİ”.')).toBeVisible()

  await region.getByLabel('Search everything this project remembers').fill('unicorn')
  await region.getByRole('button', { name: 'Search deeper' }).click()
  await expect(region.getByText('Nothing said in earlier messages speaks to “unicorn”.')).toBeVisible()
})
