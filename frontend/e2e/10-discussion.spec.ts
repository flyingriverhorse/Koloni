import { expect, test } from './fixtures'
import { openFreshConversation } from './helpers'

test('agents discuss in a shared place, and you can speak in it', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill('discuss the greeting with the others')
  await page.getByRole('button', { name: 'Send' }).click()

  // The shared place opens by itself and fills as each one speaks.
  const place = page.getByRole('region', { name: 'Discussion' })
  await expect(place.getByText('Should the greeting stay hi?')).toBeVisible()
  await expect(place.getByText('Reviewer · Researcher · Orchestrator')).toBeVisible()
  await expect(place.getByText('I would keep hi.')).toBeVisible()

  // You speak in it too; whoever speaks next has read it.
  await place.getByLabel('Say something to everyone').fill('Mind the tests.')
  await place.getByRole('button', { name: 'Say' }).click()
  await expect(place.getByText('Mind the tests.')).toBeVisible()
  await expect(place.getByText('Then we keep hi.')).toBeVisible()

  // It ends when nobody has more to say, and the lead goes on with what was decided.
  await expect(chat.getByText('We keep hi.')).toBeVisible({ timeout: 20_000 })
  await expect(place.getByText(/^Ended: /)).toBeVisible()
  await expect(place.getByLabel('Say something to everyone')).toHaveCount(0)
  await expect(place.getByText('Reviewer has nothing to add')).toBeVisible()

  // On the canvas it is one node, joined to the three who took part.
  const node = page.locator('.react-flow__node-discussion')
  await expect(node).toHaveCount(1)
  await expect(node).toContainText('Should the greeting stay hi?')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(3)
  // The user's option A (21 Nov): the two under it in its column join it round their right, into its side - no line
  // doubles back behind the cards to its left.
  const behind = () =>
    page.locator('.react-flow__edges').evaluate(() => {
      const place = document.querySelector('.react-flow__node-discussion')!.getBoundingClientRect()
      const stacked = [...document.querySelectorAll('.react-flow__edge')].flatMap(edge => {
        const [source, target] = (edge.getAttribute('data-id') ?? '').split('>')
        const card = document.querySelector(`.react-flow__node[data-id="${source}"]`)?.getBoundingClientRect()
        return target?.startsWith('discussion:') && card && Math.abs(card.x - place.x) < 1 ? [edge] : []
      })
      return { stacked: stacked.length, behind: stacked.filter(edge => edge.querySelector('path')!.getBoundingClientRect().left < place.right - 1).length }
    })
  await expect.poll(behind).toEqual({ stacked: 2, behind: 0 })

  // In the chat it is one row; what the lead said in the discussion is not chat.
  await expect(chat.getByRole('button', { name: /Discussion.*Should the greeting stay hi\?/ })).toContainText('3 agents')
  await expect(chat.getByText('Then we keep hi.')).toHaveCount(0)

  // A reload shows the same discussion from the records; the row opens it again.
  await page.reload()
  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: /Discussion/ }).click()
  const again = page.getByRole('region', { name: 'Discussion' })
  await expect(again.getByText('Mind the tests.')).toBeVisible()
  await expect(again.getByText('I would keep hi.')).toBeVisible()
})
