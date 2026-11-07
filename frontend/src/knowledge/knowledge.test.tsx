import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { KnowledgeItem, KnowledgeState, Project, Provider } from '../api/types'
import { Rail } from '../shell/Rail'
import { KnowledgePage } from './KnowledgePage'

// K-bilgi part 1: the project's Knowledge page - a card for each knowledge (layout A), opened to its tabs, with Try it, and "+ Add knowledge"
// in one window (sample D1) that names no role: roles choose on their own Knowledge tab.
const LEARNED: KnowledgeState = {
  learning: false,
  stale: null,
  failed: null,
  folder: '.koloni/knowledge/mlflow/',
  guide: '## Registry',
  estimate: 0.42,
  requests: 3,
  learned: {
    learned_at: new Date(Date.now() - 2 * 24 * 3600 * 1000).toISOString(),
    model: 'Claude Code · haiku',
    guide_from: 2,
    unread: 3,
    // (What its pages hold beyond the guide: Learn more writes it.)
    left: 90_000,
    cost: { amount: 0.18, currency: 'USD' },
    added: [],
    pages: [
      { source: 'https://mlflow.org/docs/latest/a', read: true, why: null, found: false, code: false },
      { source: 'https://mlflow.org/docs/latest/b', read: true, why: null, found: false, code: false },
      { source: 'https://mlflow.org/docs/latest/c', read: false, why: 'too long', found: false, code: false },
    ],
  },
}
const MLFLOW: KnowledgeItem = {
  id: 'k1',
  project_id: 'p1',
  knowledge: { topic: 'MLflow', sources: ['https://mlflow.org/docs/latest/'], max_pages: 20, max_usd: 1, max_code_files: 100, learn_with: null, weekly: false, search_answering: false },
  used_by: [
    { role_id: 'r1', name: 'ML engineer', mode: 'full' },
    { role_id: 'r2', name: 'Coder', mode: 'map' },
  ],
  state: LEARNED,
}
const NEW: KnowledgeItem = {
  ...MLFLOW,
  id: 'k2',
  project_id: null,
  knowledge: { ...MLFLOW.knowledge, topic: 'tomli', sources: ['docs/'] },
  used_by: [],
  state: { ...LEARNED, learned: null, stale: 'no guide yet', guide: null, estimate: null, requests: null },
}
const page = (over: object = {}) => {
  const props = {
    items: [MLFLOW, NEW],
    error: null,
    projectName: 'sifirdan-notlar',
    providers: [] as Provider[],
    otherProjects: [] as Project[],
    onReload: vi.fn().mockResolvedValue(undefined),
    onAdd: vi.fn().mockResolvedValue({ id: 'k3' }),
    onSave: vi.fn().mockResolvedValue(undefined),
    onCopy: vi.fn().mockResolvedValue(undefined),
    onReadFile: vi.fn().mockResolvedValue({ text: '## Tracking\n- mlflow.start_run()', size: 30, binary: false, too_large: false }),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onLearn: vi.fn().mockResolvedValue(undefined),
    onTry: vi.fn().mockResolvedValue('Use set_registered_model_alias (guide/registry.md:41).'),
    ...over,
  }
  render(<KnowledgePage {...props} />)
  return props
}

test('the rail has Knowledge between Memory and Triggers', () => {
  render(<Rail view="knowledge" onView={vi.fn()} theme="dark" onToggleTheme={vi.fn()} waiting={0} />)
  const names = screen.getAllByRole('button').map(one => one.getAttribute('aria-label'))
  expect(names.slice(names.indexOf('Memory'), names.indexOf('Memory') + 3)).toEqual(['Memory', 'Knowledge', 'Triggers'])
  expect(screen.getByRole('button', { name: 'Knowledge' })).toHaveAttribute('aria-pressed', 'true')
})


const card = (topic: string) => screen.getByRole('article', { name: topic })
const tab = (name: string | RegExp) => userEvent.click(screen.getByRole('tab', { name }))

test('a card says how much of what was read is in its guide, how fresh, what it spent and who uses it', async () => {
  const props = page()
  const mlflow = card('MLflow')
  // K-uzman-derin: of the pages read, those its guide is written from.
  expect(mlflow).toHaveTextContent('2 of 2 pages in the guide')
  expect(within(mlflow).getByRole('meter', { name: 'MLflow: pages in its guide' })).toHaveAttribute('value', '2')
  expect(mlflow).toHaveTextContent('Fresh: 2 days')
  expect(mlflow).toHaveTextContent('Spent: 0.18 of 1.00 USD')
  expect(mlflow).toHaveTextContent('Learns with: a role’s model')
  expect(within(mlflow).getByText('ML engineer · full')).toBeInTheDocument()
  expect(within(mlflow).getByText('Coder · map')).toBeInTheDocument()
  // Pages left for its limits: Learn more, with what it spends in sight beside it.
  const more = within(mlflow).getByRole('button', { name: 'Learn more' })
  expect(more.previousElementSibling).toHaveTextContent('≈ 0.42 USD')
  await userEvent.click(more)
  expect(props.onLearn).toHaveBeenCalledWith('k1')
  // Never learned, and every project's.
  const tomli = card('tomli')
  expect(tomli).toHaveTextContent('Fresh: not learned')
  expect(within(tomli).getByText('every project')).toHaveClass('tag')
  expect(within(tomli).getByRole('button', { name: 'Learn' })).toBeInTheDocument()
  expect(within(tomli).getByText('unknown cost')).toBeVisible()
  expect(within(tomli).queryByRole('meter')).not.toBeInTheDocument()
})

test('decision 4: the coverage sentence says only what the API says - the money limit, no known price, and Learn more with its requests', () => {
  const learned = learnedOf(LEARNED)
  const item = (id: string, state: KnowledgeState): KnowledgeItem => ({ ...MLFLOW, id, knowledge: { ...MLFLOW.knowledge, topic: id }, state })
  const two = [learned.pages[0], learned.pages[1], { ...learned.pages[0], source: 'x' }]
  page({
    items: [
      item('short', { ...LEARNED, learned: { ...learned, short: 1.25 } }),
      item('unpriced', { ...LEARNED, estimate: null, requests: 39, learned: { ...learned, pages: two } }),
      item('unpriced, no count', { ...LEARNED, estimate: null, requests: null, learned: { ...learned, pages: two } }),
      item('priced', LEARNED),
      item('done', { ...LEARNED, learned: { ...learned, left: 0 } }),
    ],
  })
  const why = (topic: string) => card(topic).querySelector('.knowledge-why')?.textContent ?? null
  expect(why('short')).toBe('The money limit stopped it: raise it to at least 1.25 USD to read further.')
  expect(within(card('short')).getByRole('button', { name: 'Learn again' })).toBeInTheDocument()
  expect(why('unpriced')).toBe('On a model with no known price one Learn stops after a set number of requests. Learn more adds the rest (≈39 requests).')
  expect(card('unpriced')).toHaveTextContent('2 of 3 pages in the guide')
  expect(why('unpriced, no count')).toBe('On a model with no known price one Learn stops after a set number of requests. Learn more adds the rest.')
  expect(why('priced')).toBe('Learn more adds the rest (≈3 requests).')
  expect(why('done')).toBeNull()
})

test('a spend not counted in USD is "—", why behind ⓘ', () => {
  page({ items: [{ ...MLFLOW, state: { ...LEARNED, learned: { ...learnedOf(LEARNED), cost: null } } }] })
  expect(card('MLflow')).toHaveTextContent('Spent: —')
  expect(within(card('MLflow')).getByRole('button', { name: 'About this' })).toHaveAccessibleDescription('A CLI’s or a plan’s use is not counted in USD.')
})

test('K-bilgi 5: a learning after the first says when it checked and how many pages changed, or up to date', () => {
  const learned = learnedOf(LEARNED)
  const at = new Date(Date.now() - 2 * 3600 * 1000).toISOString()
  const item = (id: string, changed: number) => ({ ...MLFLOW, id, knowledge: { ...MLFLOW.knowledge, topic: id }, state: { ...LEARNED, learned: { ...learned, learned_at: at, changed } } })
  page({ items: [item('a', 3), item('b', 1), item('c', 0)] })
  expect(card('a')).toHaveTextContent('checked 2 h ago · 3 pages changed')
  expect(card('b')).toHaveTextContent('checked 2 h ago · 1 page changed')
  expect(card('c')).toHaveTextContent('checked 2 h ago · up to date')
})

test('a learning that stopped at its page cap with pages left says to raise the cap; one under it does not (R168)', () => {
  const learned = learnedOf(LEARNED)
  const capped = { ...MLFLOW, knowledge: { ...MLFLOW.knowledge, max_pages: 2 } }
  page({ items: [capped] })
  expect(within(card('MLflow')).getByRole('button', { name: 'Learn more' })).toBeInTheDocument()
  expect(within(card('MLflow')).getByText('Cap reached: raise the page cap to read more')).toBeInTheDocument()
  cleanup()
  // At the cap with none left; under the cap with some left (its tries or time): nothing said.
  page({ items: [{ ...capped, state: { ...LEARNED, learned: { ...learned, unread: 0 } } }, { ...MLFLOW, id: 'k9', knowledge: { ...MLFLOW.knowledge, topic: 'Other' } }] })
  expect(screen.queryByText(/Cap reached/)).not.toBeInTheDocument()
})

test('an opened card is a tablist - Guide, Pages, Not known yet, Settings - moved through with the arrows; Try it is on the card', async () => {
  // R168: its answer is markdown, rendered as a chat message's - never ``` and ** as they are.
  const props = page({ onTry: vi.fn().mockResolvedValue('Call **set_registered_model_alias**:\n\n```python\nclient.set_registered_model_alias("m", "champion", 1)\n```\n\nSource: `guide/registry.md:41`') })
  expect(within(card('MLflow')).queryByRole('tablist')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /MLflow/ }))
  expect(screen.getByRole('button', { name: /MLflow/ })).toHaveAttribute('aria-expanded', 'true')
  const tabs = within(screen.getByRole('tablist', { name: 'MLflow' })).getAllByRole('tab')
  expect(tabs.map(one => one.textContent)).toEqual(['Guide', 'Pages · 3', 'Not known yet', 'Settings'])
  expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
  tabs[0].focus()
  await userEvent.keyboard('{ArrowLeft}')
  expect(tabs[3]).toHaveFocus()
  expect(screen.getByRole('tabpanel', { name: 'Settings' })).toBeVisible()
  expect(screen.getByLabelText('Sources')).toHaveValue('https://mlflow.org/docs/latest/')
  expect(screen.getByLabelText('Learn with')).toHaveDisplayValue('The model of a role that uses it')
  expect(screen.getByLabelText(/Agents may search the web/)).not.toBeChecked()
  await userEvent.click(within(card('MLflow')).getByRole('button', { name: 'Try it' }))
  await userEvent.type(screen.getByLabelText(/Try it/), 'How do I give a model an alias?')
  await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
  expect(props.onTry).toHaveBeenCalledWith('k1', 'How do I give a model an alias?')
  const answer = (await screen.findByText('set_registered_model_alias', { selector: 'strong' })).closest('.knowledge-answer') as HTMLElement
  expect(answer).toHaveAttribute('role', 'status')
  expect(within(answer).getByText('guide/registry.md:41', { selector: 'code' })).toBeInTheDocument()
  expect(answer.querySelector('pre')).toHaveTextContent('client.set_registered_model_alias("m", "champion", 1)')
  expect(answer).not.toHaveTextContent(/\*\*|```/)
})

test('an open card whose first learning ends turns to its Guide', async () => {
  const props = page({ items: [NEW] })
  await userEvent.click(screen.getByRole('button', { name: /tomli/ }))
  expect(screen.getByRole('tab', { name: 'Settings' })).toHaveAttribute('aria-selected', 'true')
  cleanup()
  const { rerender } = render(<KnowledgePage {...props} items={[NEW]} />)
  await userEvent.click(screen.getByRole('button', { name: /tomli/ }))
  rerender(<KnowledgePage {...props} items={[{ ...NEW, state: LEARNED }]} />)
  expect(screen.getByRole('tab', { name: 'Guide' })).toHaveAttribute('aria-selected', 'true')
})

test('Not known yet: not measured, every question answered, or what it found no page for', async () => {
  // K-bilgi 7: what a clicked learning's questions of its guide could not answer from its pages.
  const asked = (unknown: string[] | null) => ({ ...MLFLOW, state: { ...LEARNED, learned: { ...learnedOf(LEARNED), unknown } } })
  await open({ items: [asked(null)] })
  await tab('Not known yet')
  expect(screen.getByText('Not measured yet.')).toBeInTheDocument()
  cleanup()
  await open({ items: [asked([])] })
  await tab('Not known yet · 0')
  expect(screen.getByText(/answered every question/)).toBeInTheDocument()
  cleanup()
  await open({ items: [asked(['Model aliases', 'Tracing'])] })
  await tab('Not known yet · 2')
  expect(screen.getByText(/found no page for/).nextElementSibling?.textContent).toBe('Model aliasesTracing')
  expect(screen.getByText('Model aliases').tagName).toBe('LI')
  // (Its pages hold more than its guide: Learn more may cover them.)
  expect(screen.getByText('Learn more may cover them.')).toBeInTheDocument()
})

test('Add knowledge is the Settings form in its new mode: the kind on top, the page cap under More, no Used by; Add and learn adds, then learns', async () => {
  const props = page()
  await userEvent.click(screen.getByRole('button', { name: '+ Add knowledge' }))
  const window = screen.getByRole('dialog', { name: 'Add knowledge' })
  expect(within(window).queryByText(/Used by/)).not.toBeInTheDocument()
  expect(within(window).getByRole('radio', { name: /A docs site/ })).toHaveFocus()
  expect(within(window).getByLabelText('At most this many pages (a safety cap)').closest('details')).not.toHaveAttribute('open')
  const add = within(window).getByRole('button', { name: 'Add and learn' })
  expect(add).toBeDisabled()
  await userEvent.click(within(window).getByRole('radio', { name: /Research a topic/ }))
  await userEvent.type(within(window).getByLabelText('What to research'), 'stripe webhooks')
  await userEvent.type(within(window).getByLabelText('Topic'), 'Stripe')
  // A topic to research searches unless told not to: the box says so, and here it is switched off.
  const search = within(window).getByLabelText(/Agents may search the web/)
  expect(search).toBeChecked()
  await userEvent.click(search)
  await userEvent.click(add)
  expect(props.onAdd).toHaveBeenCalledWith({ topic: 'Stripe', sources: ['research: stripe webhooks'], max_pages: 500, max_usd: 0.5, max_code_files: 100, learn_with: null, removed: [], weekly: false, search_answering: false })
  expect(props.onLearn).toHaveBeenCalledWith('k3')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('Add without learning only adds; a learning that cannot start is said in the window', async () => {
  const props = page({ onLearn: vi.fn().mockRejectedValue(new Error('choose a model it learns with: no role uses it')) })
  await userEvent.click(screen.getByRole('button', { name: '+ Add knowledge' }))
  await userEvent.type(screen.getByLabelText('Address'), 'https://docs.test/')
  await userEvent.type(screen.getByLabelText('Topic'), 'Docs')
  await userEvent.click(screen.getByRole('button', { name: 'Add and learn' }))
  expect(await screen.findByText('Added, not learned: choose a model it learns with: no role uses it')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await userEvent.click(screen.getByRole('button', { name: '+ Add knowledge' }))
  await userEvent.type(screen.getByLabelText('Address'), 'https://docs.test/')
  await userEvent.type(screen.getByLabelText('Topic'), 'Docs')
  await userEvent.click(screen.getByRole('button', { name: 'Add without learning' }))
  expect(props.onAdd).toHaveBeenCalledTimes(2)
  // Its web search not touched: not sent, the server's default.
  expect(props.onAdd.mock.calls[1][0]).not.toHaveProperty('search_answering')
  expect(props.onLearn).toHaveBeenCalledTimes(1)
})

// K-bilgi E (R163): what the role's Knowledge tab had - its sources and limits, its pages, its guide, copying it - is the card's.
const open = async (over: object = {}) => {
  const props = page(over)
  await userEvent.click(screen.getByRole('button', { name: /MLflow/ }))
  return props
}
const learnedOf = (state: KnowledgeState) => state.learned as NonNullable<KnowledgeState['learned']>

test('its sources and limits are changed and saved in Settings, with the page cap in sight; its topic stays; new sources say Learn again reads them', async () => {
  const props = await open()
  await tab('Settings')
  expect(screen.getByText(/it names its folder, .koloni\/knowledge\/mlflow\//)).toBeInTheDocument()
  expect(screen.queryByLabelText('Topic')).not.toBeInTheDocument()
  expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
  expect(screen.getByLabelText('At most this many pages (a safety cap)').closest('details')).toBeNull()
  await userEvent.clear(screen.getByLabelText('Sources'))
  await userEvent.type(screen.getByLabelText('Sources'), 'https://mlflow.org/docs/latest/\ndocs/mlflow.md')
  await userEvent.clear(screen.getByLabelText(/At most this much/))
  await userEvent.type(screen.getByLabelText(/At most this much/), '2')
  await userEvent.click(screen.getByLabelText(/Agents may search the web/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(props.onSave).toHaveBeenCalledWith('k1', {
    topic: 'MLflow',
    sources: ['https://mlflow.org/docs/latest/', 'docs/mlflow.md'],
    max_pages: 20,
    max_usd: 2,
    max_code_files: 100,
    learn_with: null,
    removed: [],
    weekly: false,
    search_answering: true,
  })
  expect(await screen.findByText('Saved: Learn again reads the new sources.')).toHaveAttribute('role', 'status')
})

test('a refusal to save is said as the server says it', async () => {
  await open({ onSave: vi.fn().mockRejectedValue(new ApiError(422, 'unknown provider')) })
  await tab('Settings')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('unknown provider')
})

test('B-365: a model chosen to learn with is saved, then learned with; another tab keeps what was typed', async () => {
  const CODEX = { id: 'cx', name: 'Codex', default_model: 'gpt-6-luna', models: [] } as unknown as Provider
  const props = await open({ providers: [CODEX] })
  await tab('Settings')
  await userEvent.selectOptions(screen.getByLabelText('Learn with'), 'cx gpt-6-luna')
  // The card's own Learn would learn with what is saved: held until it is - on any tab.
  await tab('Guide')
  expect(screen.getByRole('button', { name: 'Learn more' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Learn more' })).toHaveAttribute('title', 'Save first: Save and learn uses what you changed')
  await tab('Settings')
  await userEvent.click(screen.getByRole('button', { name: 'Save and learn' }))
  expect(props.onSave.mock.calls[0][1].learn_with).toEqual({ provider_id: 'cx', model_id: 'gpt-6-luna' })
  expect(props.onLearn).toHaveBeenCalledWith('k1')
  expect(props.onSave.mock.invocationCallOrder[0]).toBeLessThan(props.onLearn.mock.invocationCallOrder[0])
})

test('its pages say what was read and skipped and why', async () => {
  await open()
  expect(screen.getByText(/learned .* on Claude Code · haiku/)).toBeInTheDocument()
  await tab(/^Pages/)
  expect(screen.getByText('Pages: 2 read, 1 skipped, 3 more not read (its limits)')).toBeVisible()
  const skipped = screen.getByText(/skipped https:\/\/mlflow.org\/docs\/latest\/c/)
  expect(within(skipped).getByText('· too long')).toBeInTheDocument()
})

// K-uzman part 2: a topic to research - its labels, the version warning, the pages it found and what was found while answering.
const RESEARCHED: KnowledgeState = {
  ...LEARNED,
  version_warning: 'docs are for v2, the project has v1.4.2',
  learned: {
    ...learnedOf(LEARNED),
    unread: 0,
    labels: { official: 2, 'single source': 1, unsure: 0 },
    added: [{ text: 'Retries stop after 3 days', source: 'https://forum.test/t/9' }],
    pages: [
      { source: 'https://pay.test/v2/a', read: true, why: null, found: true, code: false },
      { source: 'https://blog.test/post', read: true, why: null, found: true, code: false },
    ],
  },
}
const researching = { ...MLFLOW, knowledge: { ...MLFLOW.knowledge, sources: ['research: pay webhooks'] }, state: RESEARCHED }

test('a researched knowledge says its labels and version, and a page it found is taken off its list', async () => {
  const props = await open({ items: [researching] })
  expect(screen.getByText(/Entries: 2 official, 1 single source/)).toBeInTheDocument()
  expect(screen.getByText('Version: docs are for v2, the project has v1.4.2.')).toBeInTheDocument()
  await tab(/^Pages/)
  await userEvent.click(screen.getByRole('button', { name: 'Remove https://blog.test/post' }))
  expect(props.onSave.mock.calls[0][0]).toBe('k1')
  expect(props.onSave.mock.calls[0][1].removed).toEqual(['https://blog.test/post'])
  expect(await screen.findByText('Removed: Learn again to leave it out of the guide.')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Found while answering: 1, each a single source'))
  await userEvent.click(screen.getByRole('button', { name: 'Remove Retries stop after 3 days' }))
  expect(props.onSave.mock.calls[1][1].removed).toEqual(['https://forum.test/t/9'])
})

test('a topic to research or a site can be learned again weekly; with only files, it is not offered', async () => {
  const props = await open({ items: [researching] })
  await tab('Settings')
  await userEvent.click(screen.getByLabelText(/Learn again weekly/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(props.onSave.mock.calls[0][1]).toMatchObject({ sources: ['research: pay webhooks'], weekly: true })
  await userEvent.clear(screen.getByLabelText('Sources'))
  await userEvent.type(screen.getByLabelText('Sources'), 'docs/pay.md')
  expect(screen.queryByLabelText(/Learn again weekly/)).not.toBeInTheDocument()
  // K-bilgi 5: a site's changed pages are read again weekly.
  await userEvent.clear(screen.getByLabelText('Sources'))
  await userEvent.type(screen.getByLabelText('Sources'), 'https://docs.test/pay')
  expect(screen.getByLabelText(/Learn again weekly/)).toBeInTheDocument()
})

test('the guide reads as its map, and each of its sections opens on its own', async () => {
  const guide = '## Registry\n- aliases\n\n## Sections\n- guide/0123456789ab.md: https://mlflow.org/docs/latest/a (pages/0001.md to 0002.md)'
  const props = await open({ items: [{ ...MLFLOW, state: { ...LEARNED, guide } }] })
  expect(screen.getByText('Learning again with another model rewrites only the map: its sections are kept.')).toBeInTheDocument()
  expect(screen.getByText(/- aliases/)).toBeVisible()
  await userEvent.click(screen.getByText('guide/0123456789ab.md'))
  expect(props.onReadFile).toHaveBeenCalledWith('.koloni/knowledge/mlflow/guide/0123456789ab.md')
  expect(await screen.findByText(/mlflow.start_run\(\)/)).toBeInTheDocument()
})

const PROJECTS = [{ id: 'p2', name: 'billing' }] as unknown as Project[]

test('the guide is copied into another project from its Copy tab; one there already is replaced only on the user’s yes', async () => {
  const there = new ApiError(409, 'there is a guide there already: replace it, and the pages read there?')
  const onCopy = vi.fn().mockRejectedValueOnce(there).mockResolvedValue(undefined)
  // B-337: KOLONİ's own question, never the browser's.
  const confirm = vi.spyOn(window, 'confirm')
  await open({ otherProjects: PROJECTS, onCopy })
  await tab('Copy')
  const button = screen.getByRole('button', { name: 'Copy guide' })
  expect(button).toBeDisabled()
  await userEvent.selectOptions(screen.getByLabelText('Copy the guide to'), 'p2')
  await userEvent.click(button)
  expect(onCopy).toHaveBeenCalledWith('k1', 'p2', undefined)
  const asked = await screen.findByRole('alertdialog', { name: 'billing has a guide of MLflow already. Replace it? The pages read there are deleted.' })
  await userEvent.click(within(asked).getByRole('button', { name: 'Replace it' }))
  expect(onCopy).toHaveBeenLastCalledWith('k1', 'p2', true)
  // B-131: said beside the button.
  expect(await screen.findByText('Guide copied to billing.')).toBe(button.nextElementSibling)
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

// K-bilgi 8: this project's code - offered in one line until it is scanned, then a card like the others that rescans for free.
test('the code is offered for a scan, then its card says when, how many files and names, and rescans', async () => {
  const props = page({ items: [MLFLOW] })
  await userEvent.click(screen.getByRole('button', { name: 'Scan the code' }))
  expect(props.onAdd).toHaveBeenCalledWith(expect.objectContaining({ sources: ['code:'] }))
  expect(props.onLearn).toHaveBeenCalledWith('k3')
  cleanup()
  const scanned = { ...LEARNED.learned!, learned_at: new Date(Date.now() - 3 * 60_000).toISOString(), model: 'a scan of the code, no model', guide_from: 48, symbols: 312, cost: { amount: 0, currency: 'USD' }, left: 0 }
  const code: KnowledgeItem = { ...NEW, id: 'kc', project_id: 'p1', knowledge: { ...NEW.knowledge, topic: 'This project’s code', sources: ['code:'] }, state: { ...LEARNED, learned: scanned, stale: null, estimate: null } }
  const again = page({ items: [MLFLOW, code] })
  expect(screen.queryByRole('button', { name: 'Scan the code' })).not.toBeInTheDocument()
  const scannedCard = card('This project’s code')
  expect(scannedCard).toHaveTextContent('scanned from the project')
  expect(scannedCard).toHaveTextContent('Scanned: 3 min ago')
  expect(scannedCard).toHaveTextContent('48 files · 312 symbols')
  expect(within(scannedCard).getByText('free · only changed files')).toBeInTheDocument()
  expect(within(scannedCard).queryByRole('meter')).not.toBeInTheDocument()
  await userEvent.click(within(scannedCard).getByRole('button', { name: 'Rescan' }))
  expect(again.onLearn).toHaveBeenCalledWith('kc')
})

test('Project notes: its notes counted, nothing to learn or to set, Try it as any knowledge', async () => {
  // K-bilgi 6: written from what the user accepted at a turn's end - no Learn, no sources, no cost.
  const notes: KnowledgeItem = {
    ...MLFLOW,
    id: 'k7',
    knowledge: { ...MLFLOW.knowledge, topic: 'Project notes', sources: ['notes:'] },
    state: { ...LEARNED, estimate: null, requests: null, learned: { ...LEARNED.learned!, guide_from: 2, cost: null, left: 0, pages: LEARNED.learned!.pages.slice(0, 2) } },
  }
  page({ items: [notes] })
  expect(card('Project notes')).toHaveTextContent('2 notes')
  expect(screen.getByText('written as you accept them')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Learn/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Project notes/ }))
  expect(screen.queryByLabelText('Sources')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: /Not known yet/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Try it' }))
  expect(screen.getByLabelText(/Try it/)).toBeInTheDocument()
})

test('Try it says the model that will answer before you ask, and is off where none can', async () => {
  // B-372: a knowledge no role uses answers on a new chat's model - maybe a paid one, so it is said first.
  const paid: KnowledgeItem = { ...NEW, id: 'k8', state: { ...NEW.state, answers_on: 'apikeysub · sonnet', per_token: true } }
  page({ items: [paid] })
  await userEvent.click(screen.getByRole('button', { name: 'Try it' }))
  expect(screen.getByText('Answers on apikeysub · sonnet')).toHaveAttribute('title', 'apikeysub · sonnet (a pay-per-token provider)')
  expect(screen.getByLabelText(/Try it/)).toBeEnabled()
  cleanup()
  const none: KnowledgeItem = { ...paid, state: { ...NEW.state, answers_refused: 'no model provider is set up' } }
  page({ items: [none] })
  await userEvent.click(screen.getByRole('button', { name: 'Try it' }))
  expect(screen.getByText('No model can answer it: no model provider is set up')).toBeInTheDocument()
  expect(screen.getByLabelText(/Try it/)).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
})

// KOLONİ's own guide: one click adds it - only its docs/, on the server - and learning waits for Learn (it costs model calls).
test('KOLONİ’s own guide is added in one click, not learned, and offered no more once added', async () => {
  const props = page({ items: [MLFLOW] })
  await userEvent.click(screen.getByRole('button', { name: 'Add KOLONİ’s own guide' }))
  expect(props.onAdd).toHaveBeenCalledWith({ topic: 'KOLONİ guide', sources: ['koloni-guide:'], max_usd: 0.5, learn_with: null })
  expect(props.onLearn).not.toHaveBeenCalled()
  cleanup()
  const guide: KnowledgeItem = { ...NEW, id: 'kg', project_id: 'p1', knowledge: { ...NEW.knowledge, topic: 'KOLONİ guide', sources: ['koloni-guide:'] } }
  page({ items: [MLFLOW, guide] })
  expect(screen.queryByRole('button', { name: 'Add KOLONİ’s own guide' })).not.toBeInTheDocument()
})

// K-bilgi-repo: a repository - its docs' line as any card's, then its code files in the guide and its free code map.
test('a repository card adds its code files in the guide and its free code map; a docs site has neither', async () => {
  const repo: KnowledgeItem = {
    ...MLFLOW,
    id: 'kr',
    knowledge: { ...MLFLOW.knowledge, topic: 'Pay', sources: ['repo: https://github.com/acme/pay'] },
    state: {
      ...LEARNED,
      learned: {
        ...LEARNED.learned!,
        left: 0,
        guide_from: 2,
        pages: [
          { source: 'README.md', read: true, why: null, found: false, code: false },
          { source: 'docs/a.md', read: true, why: null, found: false, code: false },
          { source: 'main.py', read: true, why: null, found: false, code: true },
        ],
        code: { scanned: 340, symbols: 900, ranked: 3, in_guide: ['main.py'], left: [], stopped: 'the code-file cap (1)' },
      },
    },
  }
  page({ items: [repo, MLFLOW] })
  const pay = card('Pay')
  expect(pay).toHaveTextContent('2 of 2 pages in the guide')
  expect(pay).toHaveTextContent('1 of 3 code files in the guide · stopped by the code-file cap (1)')
  expect(pay).toHaveTextContent('Code map: 340 files scanned · free')
  expect(within(pay).getByRole('meter', { name: 'Pay: code files in its guide' })).toHaveAttribute('value', '1')
  // Code files left: Learn more goes on with them; what it spends is beside it, the code map free.
  const more = within(pay).getByRole('button', { name: 'Learn more' })
  expect(more.previousElementSibling).toHaveTextContent('≈ 0.42 USD · code map free')
  const mlflow = card('MLflow')
  expect(mlflow).not.toHaveTextContent('code files in the guide')
  expect(mlflow).not.toHaveTextContent('Code map')
})

test('a repository is added from its address, with its code-file cap under More', async () => {
  const props = page()
  await userEvent.click(screen.getByRole('button', { name: '+ Add knowledge' }))
  const window = screen.getByRole('dialog', { name: 'Add knowledge' })
  const kind = within(window).getByRole('radio', { name: /A repository/ })
  expect(kind).toHaveTextContent('its code (a free scan) and a guide from its docs and code')
  await userEvent.click(kind)
  expect(within(window).getByLabelText('Address')).toHaveAttribute('placeholder', 'https://github.com/owner/name')
  await userEvent.type(within(window).getByLabelText('Address'), 'https://github.com/acme/pay')
  await userEvent.type(within(window).getByLabelText('Topic'), 'Pay')
  const cap = within(window).getByLabelText('At most this many code files a learning')
  expect(cap.closest('details')).not.toHaveAttribute('open')
  await userEvent.clear(cap)
  await userEvent.type(cap, '40')
  await userEvent.click(within(window).getByRole('button', { name: 'Add and learn' }))
  expect(props.onAdd).toHaveBeenCalledWith({ topic: 'Pay', sources: ['repo: https://github.com/acme/pay'], max_pages: 500, max_usd: 0.5, max_code_files: 40, learn_with: null, removed: [], weekly: false })
})

test('a folder on this machine is added by its full path, as a repository is, with its code-file cap', async () => {
  const props = page()
  await userEvent.click(screen.getByRole('button', { name: '+ Add knowledge' }))
  const window = screen.getByRole('dialog', { name: 'Add knowledge' })
  await userEvent.click(within(window).getByRole('radio', { name: /A folder on this machine/ }))
  const path = within(window).getByLabelText('Full path')
  expect(path).toHaveAttribute('placeholder', 'C:\\work\\mylib')
  await userEvent.type(path, 'C:\\work\\mylib')
  await userEvent.type(within(window).getByLabelText('Topic'), 'Mylib')
  expect(within(window).getByLabelText('At most this many code files a learning')).toHaveValue('100')
  await userEvent.click(within(window).getByRole('button', { name: 'Add and learn' }))
  expect(props.onAdd).toHaveBeenCalledWith({ topic: 'Mylib', sources: ['folder: C:\\work\\mylib'], max_pages: 500, max_usd: 0.5, max_code_files: 100, learn_with: null, removed: [], weekly: false })
})
