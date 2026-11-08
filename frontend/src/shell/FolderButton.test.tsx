import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import type { FolderBrowse, Folders, ListedConversation, Project } from '../api/types'
import { conversation } from '../test-fixtures'
import { FolderBrowser } from './FolderBrowser'
import { FolderButton } from './FolderButton'
import { HOLDS, WIDE } from './Folders'

afterEach(() => vi.restoreAllMocks())

const folder = (id: string, name: string, created_at = '2026-10-01T00:00:00Z') => ({ id, name, root_path: `C:\\work\\${name}`, created_at }) as Project
const chat = (id: string, project_id: string | null, updated_at: string): ListedConversation => ({ ...conversation, id, project_id, updated_at, kept: false, backlog_task: null, wrote: false, archived_at: null })
const [agent, game, notes] = [folder('a', 'Skyulf-Agent'), folder('g', 'oyun-projesi'), folder('n', 'notes')]

const listing = (path: string, entries: Partial<FolderBrowse['entries'][number]>[] = []): FolderBrowse => {
  const names = path.split('\\')
  return {
    path,
    parts: names.map((name, at) => ({ name: at === 0 ? `${name}\\` : name, path: names.slice(0, at + 1).join('\\') })),
    shortcuts: [{ name: 'Home', path: 'C:\\Users\\me' }],
    entries: entries.map(entry => ({ name: 'x', path: `${path}\\${entry.name}`, koloni: false, git: false, hidden: false, blocked: false, ...entry })),
    more: false,
  }
}

function button(over: Partial<Parameters<typeof FolderButton>[0]> = {}) {
  const props = {
    project: agent,
    projects: [agent, game, notes],
    // (the latest first, as the server lists them)
    conversations: [chat('c1', 'n', '2026-10-24T09:00:00Z'), chat('c2', 'a', '2026-10-24T08:00:00Z'), chat('c3', 'g', '2026-10-20T08:00:00Z')],
    conversation: null,
    onFolders: vi.fn(async () => {}),
    onDefault: vi.fn(async () => {}),
    onMove: vi.fn(async () => {}),
    onPart: vi.fn(async () => {}),
    onNew: vi.fn(async () => {}),
    onOpenFolder: vi.fn(async (path: string) => folder('new', path.split('\\').at(-1)!)),
    onBrowse: vi.fn(async (path: string | null) => listing(path ?? 'C:\\Users\\me')),
    ...over,
  }
  render(
    <div className="app">
      <FolderButton {...props} />
    </div>,
  )
  return props
}

const panel = () => screen.getByRole('dialog', { name: 'This chat’s folders' })

test('the button says the main folder or "No folder"; its panel has the main folder, then the folders to switch to by last use, "Open a folder…" and "No folder"', async () => {
  const { onMove } = button()
  const shown = screen.getByRole('button', { name: 'Folder: Skyulf-Agent' })
  expect(shown).toHaveTextContent('Skyulf-Agent')
  await userEvent.click(shown)
  expect(within(panel()).getByText('C:\\work\\Skyulf-Agent')).toBeInTheDocument()
  // The folders to switch to are behind "Change".
  expect(within(panel()).queryByRole('region', { name: 'Switch the main folder' })).toBeNull()
  await userEvent.click(within(panel()).getByRole('button', { name: /^Change/ }))
  const choices = within(within(panel()).getByRole('region', { name: 'Switch the main folder' })).getAllByRole('button').map(b => b.textContent)
  expect(choices).toEqual([expect.stringMatching(/^notesC:\\work\\notes · /), expect.stringMatching(/^oyun-projesiC:\\work\\oyun-projesi · /), 'Open a folder…', 'No folder · a plain chat'])
  await userEvent.click(within(panel()).getByRole('button', { name: /^oyun-projesi/ }))
  expect(onMove).toHaveBeenCalledWith('g')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('a plain chat says "No folder", shows the folders to switch to at once, and offers no "No folder"', async () => {
  button({ project: null })
  await userEvent.click(screen.getByRole('button', { name: 'Folder: No folder' }))
  const choices = within(within(panel()).getByRole('region', { name: 'Switch the main folder' })).getAllByRole('button').map(b => b.textContent)
  expect(choices).toHaveLength(4)
  expect(choices.at(-1)).toBe('Open a folder…')
})

// K-buyuk-proje: the folder's map, as GET /projects/{id}/map says it (only the paths are read).
const mapOf = (...paths: string[]) => ({ parts: paths.map(path => ({ path })) })

// The places never opened, as GET /folders says them: here KOLONİ's own, on the Desktop.
const never: Folders = { never: [{ path: 'C:\\Users\\me\\Desktop\\koloni', why: 'it is KOLONİ’s own code and settings' }] }
const withDocs = { ...agent, also_in: [], read_in: ['D:\\docs'] } as unknown as Project
function inChat(lists: { also_in: string[]; read_in: string[] }, over: Partial<Parameters<typeof FolderButton>[0]> = {}) {
  vi.spyOn(api, 'get').mockImplementation(async (url: string) => (url === '/folders' ? never : mapOf('./')))
  return button({ project: withDocs, conversation: { ...conversation, ...lists }, ...over })
}
const alsoIn = () => within(panel()).getByRole('region', { name: 'Also in this chat' })

test('the chat’s other folders change, and another main folder is picked, at any time (a chat with a turn keeps its own: slice 86e)', async () => {
  const { onFolders, onMove } = inChat({ also_in: ['C:\\api'], read_in: [] })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: Skyulf-Agent/ }))
  // (Write access is taken back mid-turn too.)
  await userEvent.click(within(alsoIn()).getByRole('button', { name: 'Access to C:\\api: read & write; click for read' }))
  expect(onFolders).toHaveBeenLastCalledWith({ also_in: [], read_in: ['C:\\api'] })
  await userEvent.click(within(panel()).getByRole('button', { name: /^Change/ }))
  await userEvent.click(within(within(panel()).getByRole('region', { name: 'Switch the main folder' })).getByRole('button', { name: /^notes/ }))
  expect(onMove).toHaveBeenCalledWith('n')
})

test('the button counts the chat’s other folders; with none it has no count', async () => {
  inChat({ also_in: ['C:\\api'], read_in: ['C:\\api', 'D:\\docs'] })
  const shown = screen.getByRole('button', { name: 'Folder: Skyulf-Agent, and 2 more folders in this chat' })
  expect(shown).toHaveTextContent('+2')
})

test('with no other folder the button has no count', () => {
  inChat({ also_in: [], read_in: [] })
  expect(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' })).not.toHaveTextContent('+')
})

test('its panel lists each other folder, shortened, with its access, which a click turns; × takes one off', async () => {
  const { onFolders } = inChat({ also_in: ['C:\\api'], read_in: ['C:\\Users\\me\\Desktop\\Skyulf'] })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: Skyulf-Agent, and 2 more folders/ }))
  expect(within(alsoIn()).getByText('Desktop\\Skyulf')).toHaveAttribute('title', 'C:\\Users\\me\\Desktop\\Skyulf')
  const read = within(alsoIn()).getByRole('button', { name: 'Access to C:\\Users\\me\\Desktop\\Skyulf: read; click for read & write' })
  expect(read).toHaveTextContent(/^read$/)
  expect(within(alsoIn()).getByRole('button', { name: 'Access to C:\\api: read & write; click for read' })).toHaveTextContent('read & write')
  await userEvent.click(read)
  expect(onFolders).toHaveBeenLastCalledWith({ also_in: ['C:\\api', 'C:\\Users\\me\\Desktop\\Skyulf'], read_in: [] })
  await userEvent.click(within(alsoIn()).getByRole('button', { name: 'Remove C:\\api from this chat' }))
  expect(onFolders).toHaveBeenLastCalledWith({ also_in: [], read_in: ['C:\\Users\\me\\Desktop\\Skyulf'] })
})

test('a chat not in this folder, or a plain chat, has no other folders in the panel', async () => {
  button()
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  expect(within(panel()).queryByRole('region', { name: 'Also in this chat' })).toBeNull()
})

test('a folder is added from KOLONİ’s folder browser, to read at first; one refused says why in the browser', async () => {
  const onFolders = vi.fn().mockRejectedValueOnce(new ApiError(422, "'C:\\work\\Skyulf' is never opened")).mockResolvedValue(undefined)
  const { onBrowse } = inChat({ also_in: [], read_in: [] }, { onFolders, onBrowse: vi.fn(async (path: string | null) => listing(path ?? 'C:\\Users\\me', [{ name: 'Skyulf', git: true }])) })
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  await userEvent.click(within(alsoIn()).getByRole('button', { name: '+ Add a folder' }))
  // (beside the main folder)
  expect(onBrowse).toHaveBeenCalledWith('C:\\work')
  const browser = await screen.findByRole('dialog', { name: 'Add a folder' })
  await userEvent.click(await within(browser).findByRole('button', { name: /^Skyulf/ }))
  await userEvent.click(within(browser).getByRole('button', { name: 'Add "Skyulf"' }))
  expect(onFolders).toHaveBeenLastCalledWith({ also_in: [], read_in: ['C:\\work\\Skyulf'] })
  expect(await within(browser).findByRole('alert')).toHaveTextContent('is never opened')
  await userEvent.click(within(browser).getByRole('button', { name: 'Add "Skyulf"' }))
  expect(screen.queryByRole('dialog', { name: 'Add a folder' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' })).toHaveFocus()
})

test('the other folders are saved as the folder’s default only where they are not that already', async () => {
  const { onDefault } = inChat({ also_in: ['C:\\api'], read_in: ['D:\\docs'] })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: / }))
  await userEvent.click(within(alsoIn()).getByRole('button', { name: 'Save as this folder’s default' }))
  expect(onDefault).toHaveBeenCalledWith({ also_in: ['C:\\api'], read_in: ['D:\\docs'] })
})

test('one folder of the chat is kept for the project: added to its default at that access, the rest of it as it was', async () => {
  // (D:\docs is the project's to read in already; the chat writes in it now.)
  const { onDefault } = inChat({ also_in: ['C:\\api', 'D:\\docs'], read_in: ['E:\\notes'] })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: / }))
  await userEvent.click(within(alsoIn()).getByRole('button', { name: 'Keep C:\\api for this project' }))
  expect(onDefault).toHaveBeenLastCalledWith({ also_in: ['C:\\api'], read_in: ['D:\\docs'] })
  await userEvent.click(within(alsoIn()).getByRole('button', { name: 'Keep D:\\docs for this project' }))
  expect(onDefault).toHaveBeenLastCalledWith({ also_in: ['D:\\docs'], read_in: [] })
})

test('a folder the project keeps already, at that access or to write in, or inside one, is not offered again', async () => {
  inChat({ also_in: ['D:\\docs\\api'], read_in: ['D:\\docs', 'E:\\notes'] }, { project: { ...withDocs, also_in: ['D:\\docs'], read_in: [] } })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: / }))
  expect(within(alsoIn()).getAllByRole('button', { name: /^Keep / }).map(b => b.getAttribute('aria-label'))).toEqual([
    'Keep E:\\notes for this project',
  ])
})

test.each([
  ['the folder’s own defaults', ['D:\\docs']],
  ['the same folders in another order', ['D:\\b', 'D:\\a']],
])('with %s there is nothing to save', async (_, read_in) => {
  inChat({ also_in: [], read_in }, { project: { ...withDocs, read_in: ['D:\\docs', 'D:\\a', 'D:\\b'].filter(f => read_in.includes(f)) } })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: / }))
  expect(within(alsoIn()).queryByRole('button', { name: 'Save as this folder’s default' })).toBeNull()
})

test('a folder that holds a place never opened says only KOLONİ’s tools work there, and read & write on it that it is wide', async () => {
  inChat({ also_in: ['C:\\Users\\me\\Desktop'], read_in: ['D:\\docs'] })
  await userEvent.click(screen.getByRole('button', { name: /^Folder: / }))
  expect(await within(alsoIn()).findByText(`C:\\Users\\me\\Desktop: ${HOLDS}`)).toBeInTheDocument()
  expect(within(alsoIn()).getByText(`C:\\Users\\me\\Desktop: ${WIDE}`)).toBeInTheDocument()
  // (one that holds none: neither)
  expect(within(alsoIn()).queryByText(/^D:\\docs: /)).toBeNull()
})

test('a chat that changed files keeps its folder: the server’s reason is said, and a new chat in the other folder is offered', async () => {
  const why = 'this chat changed files in Skyulf-Agent; open a new chat for oyun-projesi'
  const { onNew } = button({ onMove: vi.fn(async () => Promise.reject(new ApiError(409, why))) })
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  await userEvent.click(within(panel()).getByRole('button', { name: /^Change/ }))
  await userEvent.click(within(panel()).getByRole('button', { name: /^oyun-projesi/ }))
  expect(within(panel()).getByRole('alert')).toHaveTextContent(why)
  await userEvent.click(within(panel()).getByRole('button', { name: 'Open a new chat in oyun-projesi' }))
  expect(onNew).toHaveBeenCalledWith('g')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('"Open a folder…" opens the browser beside the folder used last; the folder opened there is made a project and the chat’s', async () => {
  const { onBrowse, onOpenFolder, onMove } = button()
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  await userEvent.click(within(panel()).getByRole('button', { name: /^Change/ }))
  await userEvent.click(within(panel()).getByRole('button', { name: 'Open a folder…' }))
  const browser = await screen.findByRole('dialog', { name: 'Open a folder' })
  expect(onBrowse).toHaveBeenCalledWith('C:\\work')
  expect(browser).toHaveFocus()
  // Nothing behind it is reached while it is open: it stands beside the app, which is inert.
  const app = document.querySelector('.app')!
  expect(app).toHaveAttribute('inert')
  expect(app.contains(browser)).toBe(false)
  await userEvent.click(within(browser).getByRole('button', { name: 'Open "work"' }))
  expect(onOpenFolder).toHaveBeenCalledWith('C:\\work')
  expect(onMove).toHaveBeenCalledWith('new')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(app).not.toHaveAttribute('inert')
  expect(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' })).toHaveFocus()
})

test('the browser lists folders with their marks; a blocked one is faded and never chosen, though one goes inside it; double-click, Enter and the path move about', async () => {
  const onBrowse = vi.fn(async (path: string | null) =>
    path === 'C:\\Users\\me'
      ? { ...listing(path, [{ name: 'Skyulf-Agent', koloni: true, git: true }, { name: 'Skyulf', git: true }, { name: '.ssh', hidden: true, blocked: true }]), more: true }
      : listing(path ?? '?', path?.endsWith('Skyulf') ? [{ name: 'src' }] : []),
  )
  const onOpen = vi.fn(async () => {})
  render(<FolderBrowser start="C:\Users\me" onBrowse={onBrowse} onOpen={onOpen} onCancel={() => {}} />)
  const list = await screen.findByRole('list', { name: 'Folders in C:\\Users\\me' })
  const row = (name: RegExp) => within(list).getByRole('button', { name })
  expect(row(/^Skyulf-Agent/)).toHaveTextContent('Skyulf-AgentKOLONİ projectgit')
  expect(row(/^Skyulf(?!-)/)).toHaveTextContent('git')
  const ssh = row(/^\.ssh/)
  expect(ssh).toHaveTextContent('always blocked')
  expect(ssh).toHaveClass('folder-blocked', 'folder-hidden')
  expect(screen.getByText('and more…')).toBeInTheDocument()
  // Nothing chosen: Open is the folder listed; a blocked one clicked is not chosen.
  expect(screen.getByRole('button', { name: 'Open "me"' })).toBeInTheDocument()
  await userEvent.click(ssh)
  expect(ssh).not.toHaveAttribute('aria-pressed')
  expect(screen.getByRole('button', { name: 'Open "me"' })).toBeInTheDocument()
  await userEvent.click(row(/^Skyulf(?!-)/))
  expect(row(/^Skyulf(?!-)/)).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Open "Skyulf"' }))
  expect(onOpen).toHaveBeenCalledWith('C:\\Users\\me\\Skyulf')
  // Up and down go from folder to folder, Enter goes in; double-click too (into a blocked one as well).
  row(/^Skyulf-Agent/).focus()
  await userEvent.keyboard('{ArrowDown}')
  expect(row(/^Skyulf(?!-)/)).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(onBrowse).toHaveBeenLastCalledWith('C:\\Users\\me\\Skyulf')
  // (Gone in from the list, the keyboard is on the first folder inside.)
  await vi.waitFor(() => expect(row(/^src/)).toHaveFocus())
  const nav = screen.getByRole('navigation', { name: 'Where' })
  await userEvent.click(within(nav).getByRole('button', { name: 'me' }))
  await userEvent.dblClick(row(/^\.ssh/))
  expect(onBrowse).toHaveBeenLastCalledWith('C:\\Users\\me\\.ssh')
})

test('what the server refuses in the browser is said there; a start it cannot list opens at home', async () => {
  const onBrowse = vi.fn(async (path: string | null) => {
    if (path === 'C:\\gone') throw new ApiError(422, "'C:\\gone' is not an existing folder")
    return listing(path ?? 'C:\\Users\\me')
  })
  const onOpen = vi.fn(async () => Promise.reject(new ApiError(422, 'it is the home folder')))
  render(<FolderBrowser start="C:\gone" onBrowse={onBrowse} onOpen={onOpen} onCancel={() => {}} />)
  expect(await screen.findByRole('list', { name: 'Folders in C:\\Users\\me' })).toBeInTheDocument()
  expect(onBrowse).toHaveBeenLastCalledWith(null)
  await userEvent.click(screen.getByRole('button', { name: 'Open "me"' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('it is the home folder')
})

test('the chat is set to one of its folder’s parts or to the whole project (a labelled native select: the keyboard’s too); what the server refuses is said', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(mapOf('./', 'core/', 'web/'))
  const onPart = vi.fn(async (part: string | null) => {
    if (part === 'web/') throw new ApiError(422, '"web/" is not a folder of the project (a link, or gone)')
  })
  button({ project: withDocs, conversation: { ...conversation, part: 'core/' }, onPart })
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  const picker = await within(panel()).findByRole('combobox', { name: 'Agents work in' })
  expect(api.get).toHaveBeenCalledWith('/projects/a/map')
  expect(picker).toHaveValue('core/')
  expect(within(picker).getAllByRole('option').map(o => o.textContent)).toEqual(['Whole project', 'core/', 'web/'])
  await userEvent.selectOptions(picker, 'Whole project')
  expect(onPart).toHaveBeenLastCalledWith(null)
  await userEvent.selectOptions(picker, 'web/')
  expect(onPart).toHaveBeenLastCalledWith('web/')
  expect(await within(panel()).findByRole('alert')).toHaveTextContent('"web/" is not a folder of the project')
})

test('a folder whose map has no part besides its root offers no part', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(mapOf('./'))
  button({ project: withDocs, conversation })
  await userEvent.click(screen.getByRole('button', { name: 'Folder: Skyulf-Agent' }))
  await vi.waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/a/map'))
  expect(within(panel()).queryByRole('combobox')).toBeNull()
})
