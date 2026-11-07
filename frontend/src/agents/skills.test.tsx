import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { PendingSkill, Role, Skill, SkillFound, SkillPreview, SkillRecordRow } from '../api/types'
import { waitingCards } from '../chat/chatLine'
import { applyEvent } from '../state/applyEvent'
import { agent, convState } from '../test-fixtures'
import { AgentsPage } from './AgentsPage'
import { SkillsSection } from '../tools/Skills'
import { SkillApproval } from './SkillApproval'
import { SpawnApproval } from './SpawnApproval'

const found: SkillFound = {
  name: 'tidy',
  description: 'Keep changes small and plain.',
  license: 'MIT License',
  text: '---\nname: tidy\n---\nWrite the least code that works.',
  files: ['SKILL.md', 'LICENSE', 'scripts/check.py'],
  size: 2048,
  scripts: ['scripts/check.py'],
  source: 'C:\\skills\\tidy',
}
const shown = (over: Partial<SkillPreview> = {}): SkillPreview => ({
  ...found,
  script_texts: { 'scripts/check.py': "print('checked')" },
  skipped: ['.env'],
  sha256: 'sum',
  seen: { read: 1, reaches: {}, programs: [], addresses: [], env: [], whole_env: false, hidden: [], unread: [] },
  injection_rules: [],
  allowed_tools: [],
  programs: [],
  read_whole: true,
  runs_as_it_loads: [],
  shell_blocks: 0,
  ...over,
})
const skill = (over: Partial<Skill> = {}): Skill => ({
  ...found,
  id: 's1',
  folder: 'C:\\koloni\\runtime\\skills\\s1',
  scripts_run_unasked: true,
  enabled: true,
  needs: { groups: [], mcp: [], unknown: [], tools: {} },
  version: null,
  ...over,
})
const role: Role = {
  id: 'r1',
  name: 'Coder',
  description: '',
  instructions: '',
  tools: ['read_file'],
  builtin: true,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  mcp: [],
  skills: ['tidy'],
  inside_cli: false,
  knows: [],
  created_at: 't',
  updated_at: 't',
}
/** The role's Tools tab, where its skills are listed (0.1.0-ui: given on the Tools page). */
async function openTools() {
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
}
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
  onPatch: vi.fn().mockResolvedValue(undefined),
})
const NEEDS_SHELL = { groups: ['shell'], mcp: [], unknown: ['Task'], tools: { shell: ['run_command'] } }
const row = (over: Partial<SkillRecordRow> = {}): SkillRecordRow => ({
  skill: 'tidy',
  used: 3,
  in_brief: 0,
  role_name: 'Coder',
  provider_name: 'Local',
  model_id: 'big-model',
  agents: 6,
  ended: { done: 5, failed: 1, stopped_by_koloni: 0, stopped_by_user: 0, interrupted: 0 },
  steps: 12,
  seconds: null,
  input_tokens: null,
  output_tokens: null,
  changes: { taken: 0, rejected: 0 },
  compared: { chosen: 0, not_chosen: 0 },
  rediscovery: null,
  taken_in: 5,
  turned_down: 0,
  cost: null,
  ...over,
})

test("a role's skills are listed: one it cannot run says why, and each opens the Tools page on it", async () => {
  const h = handlers()
  const onOpenSkills = vi.fn()
  const ship = skill({ id: 's4', name: 'ship', description: 'Ships it.', needs: NEEDS_SHELL })
  const old = skill({ id: 's5', name: 'old', enabled: false })
  render(<AgentsPage roles={[{ ...role, skills: ['tidy', 'ship', 'old'] }]} picked="r1" skills={[skill(), ship, old]} onOpenSkills={onOpenSkills} {...h} />)
  await openTools()
  expect(screen.getByText(/1 of 3 skills/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'tidy, on the Tools page' })).toBeInTheDocument()
  // given, but the role has no shell, or it is off: said, with why
  expect(screen.getByRole('button', { name: 'ship, cannot run here: no shell, on the Tools page' })).toHaveTextContent('⚠ ship')
  expect(screen.getByRole('button', { name: 'old, cannot run here: off on the Tools page, on the Tools page' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /^ship/ }))
  expect(onOpenSkills).toHaveBeenCalledWith('ship')
  // nothing is given or taken here: no box, no editor, no window
  expect(screen.queryByRole('checkbox', { name: /^Skill / })).toBeNull()
  expect(screen.queryByLabelText('Skill folder')).toBeNull()
  expect(screen.queryByRole('complementary', { name: /^Skill / })).toBeNull()
  expect(h.onPatch).not.toHaveBeenCalled()
})

const actions = () => ({
  onPreviewSkill: vi.fn().mockResolvedValue(
    shown({ name: 'plain', license: null, scripts: ['go.sh'], script_texts: { 'go.sh': 'echo go' }, source: 'https://github.com/a/b@abc' }),
  ),
  onAddSkill: vi.fn().mockResolvedValue(skill({ id: 's2', name: 'plain' })),
  onSkillLeave: vi.fn().mockResolvedValue(undefined),
  onSkillOn: vi.fn().mockResolvedValue(undefined),
  onDeleteSkill: vi.fn().mockResolvedValue(undefined),
  onSkillRecord: vi.fn().mockResolvedValue([]),
})
/** The Tools page's SKILLS, its "Add a skill" unfolded. */
function section(skills: Skill[], a = actions(), adding = true) {
  render(<SkillsSection skills={skills} roles={[role]} off={[]} adding={adding} onAdding={vi.fn()} {...a} />)
  return a
}

test("a skill's row on the Tools page: its switch, line and roles; unfolded, its source, licence, SKILL.md, scripts' leave and how it did", async () => {
  const records = [row(), row({ provider_name: 'Qoder', model_id: 'free', agents: 2, used: 0 }), row({ provider_name: 'agy', model_id: 'flash', agents: 3, used: 0, in_brief: 3 }), row({ skill: 'notes' })]
  const a = { ...actions(), onSkillRecord: vi.fn().mockResolvedValue(records) }
  section([skill({ version: '1.2', needs: NEEDS_SHELL }), skill({ id: 's3', name: 'notes', license: null, scripts: [] })], a, false)
  const open = () => screen.getByRole('button', { name: /^tidy/ })
  // a row: its line, the role it is given to with ✗ where it cannot run, how many agents had it
  expect(open()).toHaveAttribute('aria-expanded', 'false')
  expect(open()).toHaveTextContent('Keep changes small and plain.')
  expect(open()).toHaveTextContent('✗ Coder')
  expect(await within(open()).findByText('11 agents · 30 d')).toBeInTheDocument()
  expect(screen.getByRole('switch', { name: 'tidy on' })).toBeChecked()
  await userEvent.click(screen.getByRole('switch', { name: 'tidy on' }))
  expect(a.onSkillOn).toHaveBeenCalledWith('s1', false)
  // ▾ unfolds it in place
  await userEvent.click(open())
  expect(open()).toHaveAttribute('aria-expanded', 'true')
  const tidy = document.getElementById(open().getAttribute('aria-controls')!)!
  expect(within(tidy).getByText(/v1\.2 · from C:\\skills\\tidy/)).toBeInTheDocument()
  expect(within(tidy).getByText('MIT License')).toBeInTheDocument()
  const win = within(tidy).getByRole('group', { name: 'Skill tidy' })
  expect(within(win).getByText('shell')).toBeInTheDocument()
  expect(within(win).getByText('Task (unknown)')).toBeInTheDocument()
  // its rows only, from five jobs; one never read is said so
  expect(await within(win).findByText('5/6')).toBeInTheDocument()
  expect(within(win).getAllByText('< 5 jobs')).toHaveLength(2)
  expect(within(win).getByText('given, not read')).toBeInTheDocument()
  // R190: one that could not read it was given it whole in its brief: said so, not “not read”
  expect(within(win).getByText('given in full in its brief in 3 of 3')).toBeInTheDocument()
  await userEvent.click(within(win).getByRole('button', { name: 'Steps' }))
  expect(within(win).getByText('12 steps')).toBeInTheDocument()
  await userEvent.click(within(tidy).getByText('Show SKILL.md'))
  expect(within(tidy).getByText(/Write the least code that works\./)).toBeVisible()
  await userEvent.click(within(tidy).getByLabelText('Run the scripts of tidy without asking'))
  expect(a.onSkillLeave).toHaveBeenCalledWith('s1', false)
  await userEvent.click(open())
  expect(open()).toHaveAttribute('aria-expanded', 'false')
  expect(tidy).not.toBeVisible()
})

test('a skill is given to a role or taken from it on its row, and a role that lacks a group it asks for is given that group', async () => {
  const onPatchRole = vi.fn().mockResolvedValue(undefined)
  const writer = { ...role, id: 'r2', name: 'Writer', tools: ['read_file', 'run_command'], skills: [] }
  render(
    <SkillsSection
      skills={[skill({ needs: NEEDS_SHELL })]}
      roles={[role, writer]}
      off={[]}
      picked="skill:tidy"
      adding={false}
      onAdding={vi.fn()}
      onPatchRole={onPatchRole}
      {...actions()}
    />,
  )
  // picked: open
  expect(screen.getByRole('button', { name: /^tidy/ })).toHaveAttribute('aria-expanded', 'true')
  const roles = within(screen.getByRole('group', { name: 'Skill tidy' }))
  // Coder has it but no shell: it says why, and can be taken away or given shell
  const coder = roles.getByRole('checkbox', { name: /Coder/ })
  expect(coder).toBeChecked()
  expect(coder).toBeEnabled()
  expect(coder.closest('label')).toHaveTextContent('✗ Coder (no shell)')
  await userEvent.click(roles.getByRole('button', { name: 'Give Coder shell' }))
  expect(onPatchRole).toHaveBeenLastCalledWith('r1', { tools: ['read_file', 'run_command'] })
  await userEvent.click(coder)
  expect(onPatchRole).toHaveBeenLastCalledWith('r1', { skills: [] })
  // Writer can run it and has it not: given by its box
  await userEvent.click(roles.getByRole('checkbox', { name: /Writer/ }))
  expect(onPatchRole).toHaveBeenLastCalledWith('r2', { skills: ['tidy'] })
  expect(roles.queryByRole('button', { name: 'Give Writer shell' })).toBeNull()
})

test('a skill that asks for a server switched off cannot run on a role that has the server', () => {
  const hub = skill({ needs: { groups: [], mcp: ['hub'], unknown: [], tools: {} } })
  render(<SkillsSection skills={[hub]} roles={[{ ...role, mcp: ['hub'] }]} off={[]} serversOff={['hub']} picked="skill:tidy" adding={false} onAdding={vi.fn()} onPatchRole={vi.fn()} {...actions()} />)
  expect(screen.getByRole('checkbox', { name: /Coder/ }).closest('label')).toHaveTextContent('✗ Coder (no MCP server hub)')
})

test('a role that cannot run a skill it has not got cannot be given it until it can', () => {
  render(<SkillsSection skills={[skill({ needs: NEEDS_SHELL })]} roles={[{ ...role, skills: [] }]} off={[]} picked="skill:tidy" adding={false} onAdding={vi.fn()} onPatchRole={vi.fn()} {...actions()} />)
  const coder = screen.getByRole('checkbox', { name: /Coder/ })
  expect(coder).not.toBeChecked()
  expect(coder).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Give Coder shell' })).toBeEnabled()
})

test('a skill is added from a folder after its scripts, licence and what is not copied are shown', async () => {
  const a = section([skill()])
  await userEvent.type(screen.getByLabelText('Skill folder'), 'C:\\skills\\plain{Enter}')
  expect(a.onPreviewSkill).toHaveBeenCalledWith({ folder: 'C:\\skills\\plain' })
  expect(await screen.findByText('go.sh')).toBeInTheDocument()
  expect(screen.getByText('.env')).toBeInTheDocument() // not copied, and said so
  await userEvent.click(screen.getByText('Show go.sh'))
  expect(screen.getByText('echo go')).toBeVisible()
  const leave = screen.getByLabelText('Run the scripts of plain without asking')
  expect(leave).toBeChecked()
  await userEvent.click(leave)
  await userEvent.click(screen.getByRole('button', { name: 'Add skill' }))
  expect(a.onAddSkill).toHaveBeenCalledWith({ folder: 'C:\\skills\\plain' }, false, 'sum', false)
})

test('one of a kept name is a Replace, said so; a skill is deleted only on a yes', async () => {
  const a = { ...actions(), onAddSkill: vi.fn().mockResolvedValue(skill({ id: 's2', name: 'Tidy' })) }
  a.onPreviewSkill.mockResolvedValue(shown({ name: 'Tidy' }))
  section([skill()], a)
  // no: nothing deleted; yes: deleted
  // B-337: KOLONİ's own question in the skill's row, never the browser's.
  const browser = vi.spyOn(window, 'confirm')
  await userEvent.click(screen.getByRole('button', { name: /^tidy/ }))
  const asked = () => screen.getByRole('alertdialog', { name: /^Delete the skill tidy\? Every role that has it loses it/ })
  await userEvent.click(screen.getByRole('button', { name: 'Delete skill tidy' }))
  await userEvent.click(within(asked()).getByRole('button', { name: 'Cancel' }))
  expect(a.onDeleteSkill).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Delete skill tidy' }))
  await userEvent.click(within(asked()).getByRole('button', { name: 'Delete skill' }))
  expect(a.onDeleteSkill).toHaveBeenCalledWith('s1')
  expect(browser).not.toHaveBeenCalled()
  browser.mockRestore()
  await userEvent.type(screen.getByLabelText('Skill folder'), 'C:\\skills\\tidy{Enter}')
  const replace = await screen.findByRole('button', { name: 'Replace skill' })
  expect(replace).toHaveAccessibleDescription(/is kept already: this replaces it, and the roles that have it keep it/)
  await userEvent.click(replace)
  expect(a.onAddSkill).toHaveBeenCalledWith({ folder: 'C:\\skills\\tidy' }, true, 'sum', true)
})

test('from GitHub it is added from the commit it was read at', async () => {
  const a = section([])
  await userEvent.type(screen.getByLabelText('From GitHub'), 'https://github.com/a/b')
  await userEvent.click(screen.getByRole('button', { name: 'Read from GitHub' }))
  expect(a.onPreviewSkill).toHaveBeenCalledWith({ github: 'https://github.com/a/b' })
  await userEvent.click(await screen.findByRole('button', { name: 'Add skill' }))
  expect(a.onAddSkill).toHaveBeenCalledWith({ github: 'https://github.com/a/b@abc' }, true, 'sum', false)
})

/** A file of a chosen folder, with the path the browser gives it there. */
const picked = (path: string, text: string) => {
  const file = new File([text], path.split('/').pop() ?? path)
  Object.defineProperty(file, 'webkitRelativePath', { value: path })
  return file
}

test("a chosen folder is sent as base64, without its .git, and added as it was shown", async () => {
  const a = section([])
  expect(screen.getByRole('button', { name: 'Choose folder…' })).toBeInTheDocument()
  const input = screen.getByLabelText("A skill's folder to upload")
  expect(input).toHaveAttribute('webkitdirectory')
  await userEvent.upload(input, [picked('plain/SKILL.md', 'hi'), picked('plain/.git/HEAD', 'ref')])
  const upload = { files: [{ path: 'plain/SKILL.md', data: btoa('hi') }] }
  await waitFor(() => expect(a.onPreviewSkill).toHaveBeenCalledWith({ upload }))
  await userEvent.click(await screen.findByRole('button', { name: 'Add skill' }))
  expect(a.onAddSkill).toHaveBeenCalledWith({ upload }, true, 'sum', false)
})

test('a .zip is sent whole as base64, and one larger than a .zip may be is refused here', async () => {
  const a = section([])
  expect(screen.getByRole('button', { name: 'Upload .zip…' })).toBeInTheDocument()
  const input = screen.getByLabelText("A skill's .zip to upload")
  const big = new File(['x'], 'big.zip')
  Object.defineProperty(big, 'size', { value: 25 * 1024 * 1024 + 1 })
  await userEvent.upload(input, big)
  expect(await screen.findByRole('alert')).toHaveTextContent('A skill’s .zip is at most 25 MiB')
  expect(screen.getByRole('alert')).not.toHaveTextContent('folder')
  expect(a.onPreviewSkill).not.toHaveBeenCalled()
  // one over 5 MiB (its .git, say) is sent: what it keeps is held to 5 MiB by the app
  const withGit = new File(['PK'], 'with-git.zip')
  Object.defineProperty(withGit, 'size', { value: 5 * 1024 * 1024 + 1 })
  await userEvent.upload(input, withGit)
  await waitFor(() => expect(a.onPreviewSkill).toHaveBeenCalledWith({ upload: { zip: btoa('PK') } }))
})

test('a spawn card names the skills its agent is not given, and why; a click opens one', async () => {
  const onOpenSkill = vi.fn()
  const coder = agent('r', 'proposed', { role_name: 'Researcher', skills: { given: ['tidy'], left_out: { ship: 'no shell' }, in_brief: [] } })
  render(<SpawnApproval agent={coder} onDecide={vi.fn()} onOpenSkill={onOpenSkill} />)
  expect(screen.getByText(/left out/)).toHaveTextContent('Skills: ship (no shell) left out')
  await userEvent.click(screen.getByRole('button', { name: 'ship' }))
  expect(onOpenSkill).toHaveBeenCalledWith('ship')
})

const pending: PendingSkill = {
  ...shown({ license: null }),
  tool_call_id: 'k1',
  run_id: 'r',
  agent_id: 'a',
  roles: ['Coder'],
}

test("the Lead's skill is asked about with its text, files, size, licence, scripts and roles", async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<SkillApproval skill={pending} onDecide={onDecide} />)
  expect(screen.getByText('Add this skill?')).toBeInTheDocument()
  expect(screen.getByText('licence unknown')).toBeInTheDocument()
  expect(screen.getByText(/3 files, 2\.0 KiB\./)).toBeInTheDocument()
  expect(screen.getByText(/Given to: Coder\./)).toBeInTheDocument()
  expect(screen.getByText('scripts/check.py')).toBeInTheDocument()
  expect(screen.getByText('.env')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Show scripts/check.py'))
  expect(screen.getByText("print('checked')")).toBeVisible()
  // yes without leave for its scripts
  await userEvent.click(screen.getByLabelText('Run the scripts of tidy without asking'))
  await userEvent.click(screen.getByRole('button', { name: 'Add skill' }))
  expect(onDecide).toHaveBeenCalledWith('approve', 'ask_scripts')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject', undefined)
})

test("a skill's card says what its scripts name outright, and that one which hides it cannot be trusted", () => {
  const seen = { ...pending.seen, reaches: { programs: ['subprocess'] }, programs: ['curl'], hidden: ['exec in scripts/check.py'] }
  render(<SkillApproval skill={{ ...pending, seen }} onDecide={vi.fn()} />)
  expect(screen.getByRole('alert')).toHaveTextContent('It hides what it does (exec in scripts/check.py): what is said below of it cannot be trusted.')
  expect(screen.getByText('curl')).toBeInTheDocument()
  expect(screen.getByText('What its SKILL.md tells an agent to do: read it below.')).toBeInTheDocument()
})

test('slice 92: the card lists its files, what runs as a program, its allowed-tools and the commands it would run', () => {
  const told = {
    ...pending,
    programs: ['bin/go', 'setup.bat'],
    allowed_tools: ['Read', 'Bash(git push:*)'],
    runs_as_it_loads: ['First !`git status` is read.'],
    shell_blocks: 2,
    read_whole: false,
  }
  const { rerender } = render(<SkillApproval skill={told} onDecide={vi.fn()} />)
  expect(screen.getByText(/^Its files:/)).toHaveTextContent('Its files: SKILL.md, LICENSE, scripts/check.py')
  expect(screen.getByText('scripts/check.py')).toBeInTheDocument() // its scripts, apart
  expect(screen.getByText('bin/go, setup.bat').parentElement).toHaveTextContent('Files that run as programs: bin/go, setup.bat. KOLONİ does not run them')
  expect(screen.getByText('Read, Bash(git push:*)').parentElement).toHaveTextContent('It declares allowed-tools: Read, Bash(git push:*). KOLONİ gives a skill none of them')
  expect(screen.getByText('First !`git status` is read.')).toBeInTheDocument()
  expect(screen.getByText(/Its SKILL\.md has 2 shell blocks/)).toBeInTheDocument()
  expect(screen.getByText(/a #! line in another file is not seen here/)).toBeInTheDocument()
  // none of them: it says it declares no tools, and nothing of the rest
  rerender(<SkillApproval skill={pending} onDecide={vi.fn()} />)
  expect(screen.getByText('It declares no allowed-tools.')).toBeInTheDocument()
  expect(screen.queryByText(/Files that run as programs|shell block|Claude Code would run|#! line/)).toBeNull()
})

test("a skill's card comes and goes with its events, and waits for the user", () => {
  let state = applyEvent(convState(), 1, 'skill_request.created', pending)
  expect(state.pendingSkills).toEqual([pending])
  expect(waitingCards(state)).toBe(1)
  state = applyEvent(state, 2, 'skill_request.resolved', { tool_call_id: 'k1' })
  expect(state.pendingSkills).toEqual([])
})
