import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, onTestFinished, test, vi } from 'vitest'
import type { Merge, Project, Provider, WebRequest } from '../api/types'
import { LimitsTab } from '../models/LimitsTab'
import { ModelPicker } from '../models/ModelPicker'
import { BacklogPage } from '../backlog/BacklogPage'
import { TodayView } from '../usage/TodayView'
import { OutsideApproval } from '../commands/OutsideApproval'
import { WebApproval } from '../commands/WebApproval'
import { MergeCard } from '../changes/MergeCard'
import { memoryRecord, projectMemory, toolCall } from '../test-fixtures'
import { MemoryPage } from '../memory/MemoryPage'
import { useApp } from '../state/store'
import { Hint } from './Hint'
import { ProjectSettings } from './ProjectSettings'

test('a short explanation behind ⓘ: shown while hovered, kept by a click or a key, closed by Esc - the hint only - a click elsewhere or its button', async () => {
  const panelHeard = vi.fn()
  document.addEventListener('keydown', panelHeard, true)
  render(
    <div>
      <input aria-label="Field" aria-describedby="note rest" />
      <span id="note">The first sentence.</span> <Hint id="rest">The second. And the third.</Hint>
      <button type="button">Elsewhere</button>
    </div>,
  )
  const button = screen.getByRole('button', { name: 'About this' })
  const rest = screen.getByText('The second. And the third.')
  // Closed, it is on the page all the same: the field and the button are described by it.
  expect(rest).not.toBeVisible()
  expect(screen.getByLabelText('Field')).toHaveAccessibleDescription('The first sentence. The second. And the third.')
  expect(button).toHaveAccessibleDescription('The second. And the third.')
  expect(button).toHaveAttribute('aria-expanded', 'false')

  await userEvent.hover(button)
  expect(rest).toBeVisible()
  await userEvent.unhover(button)
  await waitFor(() => expect(rest).not.toBeVisible())

  await userEvent.click(button)
  await userEvent.unhover(button)
  await new Promise(done => setTimeout(done, 200))
  expect(rest).toBeVisible()
  expect(button).toHaveAttribute('aria-expanded', 'true')
  await userEvent.keyboard('{Escape}')
  expect(rest).not.toBeVisible()
  expect(button).toHaveFocus()
  expect(panelHeard).not.toHaveBeenCalled()

  await userEvent.keyboard('{Enter}')
  expect(rest).toBeVisible()
  // The focus gone on: it would cover what the focus went to.
  await userEvent.tab()
  expect(rest).not.toBeVisible()
  await userEvent.click(button)
  expect(rest).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Elsewhere' }))
  expect(rest).not.toBeVisible()
  await userEvent.click(button)
  await userEvent.click(button)
  expect(rest).not.toBeVisible()
  document.removeEventListener('keydown', panelHeard, true)
})

const project: Project = {
  id: 'p',
  name: 'demo',
  root_path: 'C:/demo',
  created_at: 't',
  exec_location: 'host',
  docker_image: null,
  docker_network: false,
  search_url: null,
  search_order: 'builtin',
  search_agy: false,
  notify_desktop: false,
  turn_token_limit: null,
  max_agents: null,
  continue_steps: 25,
  longest_command: 10,
  monthly_budget: null,
  measure_command: null,
  after_change: 'check',
  fix_rounds: 2,
  stronger_model: true,
  check_kinds: {},
  review_lines: 80,
  review_files: 3,
  after_change_from_off: false,
  tests_found: {},
  tests_look: null,
  test_commands: {},
  full_auto_check: 'ask',
  full_auto_judge: true,
  judge_words: false,
  judge_risky: 'refuse',
  disposable_deletes: false,
  memory_links: [],
  git_commit: false,
  finish_way: null,
  auto_notes: false,
  suggest_tasks: true,
  suggest_tier: 'fast',
  day_note_at: null,
  also_in: [],
  read_in: [],
  teams_mode: 'none',
  teams: [],
  hide_secrets: true,
  canary: true,
  lead_work: 'delegates',
  when_away: 'waits',
  away_minutes: 10,
  spawn_approval: 'auto',
  spawn_max_depth: 2,
  spawn_max_agents: 6,
  spawn_max_parallel: 2,
  discussion_budget: null,
  pass_env: null,
  held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}

test('a note with a hint loses nothing: its first sentence stands, the rest is behind ⓘ, and its field points at both for its description', async () => {
  render(<ProjectSettings project={project} dockerAvailable dockerError={null} desktopAvailable onSave={vi.fn()} />)
  // (The settings are a page of sections, one shown at a time: the section is chosen first.)
  const sections = screen.getAllByRole('button').filter(button => button.classList.contains('conv-row'))
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  const field = screen.getByLabelText('At most this many agents at work in this project')
  const first = screen.getByText('Counted over all of this project’s conversations together.')
  const rest = screen.getByText(
    /^When that many are at work, a new agent .* The Chats list shows which chats are at work\.$/,
  )
  expect(first.closest('.hint')).toBeNull()
  expect(rest).not.toBeVisible()
  // The field is described by the first sentence and by the rest, in the order they were written, and not by
  // the button that opens it - closed as well as open (e2e/31 holds the browser to that).
  expect(field).toHaveAttribute('aria-describedby', `${first.id} ${rest.id}`)
  expect(field).toHaveAccessibleDescription(
    /^Counted over all of this project’s conversations together\. When that many are at work, .* holds no slot\. The Chats list shows which chats are at work\.$/,
  )
  // every hint on this page, section by section: none of them open, each with something in it;
  // and what warns of what a setting runs, spends or does not hold is never behind one: it is read before the field is set
  const warnings = [
    /they run by themselves in Full auto, or where the part’s test command is yours/,
    /the tests the sub-agent wrote or changed run in its working copy - only those/,
    /a search with it uses your plan/,
    /a CLI that reports no tokens is not limited by this/,
    /at most 90 seconds\) it holds a place like any model step, so the next message may wait for one/,
    // tek-ev: what every chat's sub-agents and discussions spend
    /Agents on a CLI that work at the same time spend your subscription at the same time/,
    /Sent and written by its speakers, together; a model that reports no tokens is not limited/,
  ]
  const warned = new Set<RegExp>()
  let hinted = 0
  expect(sections).toHaveLength(11)
  for (const section of sections) {
    await userEvent.click(section)
    const hints = Array.from(document.querySelectorAll('.hint-bubble'))
    hinted += hints.length
    for (const hint of hints) {
      expect(hint).not.toBeVisible()
      expect(hint.textContent!.trim().length).toBeGreaterThan(20)
    }
    for (const warning of warnings) {
      const shown = screen.queryByText(warning)
      if (!shown) continue
      expect(shown.closest('.hint')).toBeNull()
      warned.add(warning)
    }
  }
  expect(hinted).toBeGreaterThanOrEqual(3)
  expect(warned.size).toBe(warnings.length)
})

const local: Provider = {
  id: 'p1',
  name: 'Local',
  kind: 'openai_compat',
  base_url: 'http://127.0.0.1:8080/v1',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
}

/**
 * The other pages made plainer: what warns of what a thing runs, spends, sends or does not hold is in sight there too -
 * on the page, not behind an ⓘ nor in a closed "How this works".
 */
const elsewhere: [string, () => Promise<void>, RegExp[]][] = [
  [
    'Memory',
    async () => {
      // A preference suggested.
      useApp.setState({ projectId: 'p', projects: [project], providers: [local] })
      onTestFinished(() => useApp.setState({ projectId: null, projects: [], providers: [] }))
      const none = vi.fn(async () => {})
      const suggested = memoryRecord('s1', {
        tier: 'preference',
        status: 'proposed',
        origin: 'auto',
        text: 'short answers',
        about: null,
      })
      render(
        <MemoryPage
          memory={projectMemory({ suggestions: [suggested] })}
          onApprove={none}
          onReject={none}
          onRestore={none}
          onConfirm={none}
          onCorrect={none}
          onWrite={none}
          onSaveRules={none}
          onSaveProjectNotes={none}
          onSavePreferences={none}
          onAddPreference={none}
          onReload={none}
          onSearch={vi.fn()}
        />,
      )
      await userEvent.click(screen.getByRole('tab', { name: /^Told/ }))
    },
    [/Added, it is told to every agent in every project as your instruction\./],
  ],
  [
    'The approval cards',
    async () => {
      const card = (name: string, args: string, why_asked: string | null = null) => (
        <OutsideApproval
          call={toolCall(name, 'r', name, 'pending', args, { why_asked })}
          who="Lead"
          onDecide={vi.fn()}
        />
      )
      render(
        <>
          {card('read_file', '{"path":".env"}', 'This is a secret file.')}
          {card(
            'edit_file',
            '{"path":"C:/Users/me/.codex/config.toml"}',
            'It is Codex’s settings for this whole computer.',
          )}
          {card('ask_secret', '{"name":"API_KEY"}')}
        </>,
      )
    },
    [
      /agy started to only read does not ask\. A script that does not name the file can still read it, unless/,
      /and refused when nobody is watching\. A key in it is a secret\. One KOLONİ knows by its shape is hidden from the model\./,
      /a command you approve can still print it encoded, send it, or write it to a file/,
    ],
  ],
  [
    'To-do',
    async () => {
      const none = vi.fn(async () => {})
      render(
        <BacklogPage
          backlog={[]}
          error={null}
          providers={[]}
          onAdd={none}
          onChange={none}
          onDelete={none}
          onDecide={none}
          onOpen={vi.fn()}
        />,
      )
    },
    [
      /A task not finished gets one fix round; still not, it is stuck and the next goes on\. A stop, a restart or the month’s budget stops the chat’s queue and says why there\./,
      /a fast model, if you have one, writes the Scout’s view of it - what of what makes it done looks met: one more request, and only an opinion\. None is written for work that failed, was stopped, only made a plan or went over its turn’s token limit\./,
    ],
  ],
  [
    'Today',
    async () => {
      const day = {
        turns: 1,
        agents: ['Lead'],
        changed_files: [],
        waiting: 0,
        failed: 0,
        input_tokens: null,
        output_tokens: null,
        tokens_at_least: false,
        cost: null,
        conversations: [
          { conversation_id: 'c1', title: 'Docs', turns: 1, changed_files: 0, failed: 0, files: [], failed_runs: [] },
        ],
      }
      render(<TodayView currentId="c1" noteAt={null} onLoad={vi.fn(async () => day)} onWords={vi.fn()} />)
      await screen.findByRole('button', { name: 'Say it in words' })
    },
    [
      /a request you pay for, on the Usage page as KOLONİ itself\. It is sent the numbers above, the conversations’ titles, the changed files’ paths \(the first 20\) and the agents’ names\./,
      /With no fast model, the Orchestrator’s own model writes it, in the open conversation\./,
    ],
  ],
  [
    'The chat’s model picker',
    async () => {
      render(<ModelPicker providers={[local]} providerId={null} modelId={null} onSave={vi.fn()} />)
      await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
    },
    [/One more request for each message you send: .* It overrides the Orchestrator role’s own model and tier\./],
  ],
  [
    'Models, Limits',
    async () => {
      render(
        <>
          <LimitsTab provider={{ ...local, base_url: 'https://api.example.com/v1' }} onSave={vi.fn()} />
          <LimitsTab provider={{ ...local, id: 'cc', kind: 'claude_cli', base_url: null }} onSave={vi.fn()} />
        </>,
      )
    },
    [
      /Its runs then show no cost on Usage and count nothing in a project’s budget\./,
      /Past it, a new message whose Orchestrator runs here asks you first, a model picked by tier is the next one of its tier, and no sub-agent is opened here./,
      /A role that always runs on one tier, or on one model, is never stepped down: your own rule wins\./,
    ],
  ],
  [
    'The approval cards',
    async () => {
      // (Sample A folds what only explains a button under Details: never how far a yes reaches, nor what is deleted.)
      const web = (over: Partial<WebRequest>): WebRequest => ({
        id: 'w',
        run_id: 'r',
        agent_id: 'r',
        tool_call_id: 't',
        kind: 'search',
        method: null,
        target: 'x',
        host: null,
        headers: [],
        body_chars: null,
        status: 'proposed',
        created_at: 't',
        decided_at: null,
        ...over,
      })
      const file = {
        path: 'a.txt',
        kind: 'new',
        state: 'ready',
        whole: false,
        diff: '',
        additions: 1,
        deletions: 0,
        note: null,
      } as const
      const kept: Merge = {
        id: 'g',
        run_id: 'r',
        agent_id: 'c',
        status: 'kept',
        files: [file],
        kept_in: 'C:/copies/c',
        check: null,
        commit: null,
        created_at: 't',
        decided_at: null,
      }
      render(
        <>
          <WebApproval
            request={web({ kind: 'page', target: 'https://example.com/a', host: 'example.com' })}
            onDecide={vi.fn()}
          />
          <WebApproval
            request={web({ kind: 'http', method: 'GET', target: 'https://example.com/a', host: 'example.com' })}
            onDecide={vi.fn()}
          />
          <OutsideApproval
            call={toolCall('p', 'r', 'read_file', 'pending', '{"path":"C:/n/a.md"}', { outside_folder: 'C:/n' })}
            who="Lead"
            onDecide={vi.fn()}
          />
          <OutsideApproval
            call={toolCall('f', 'r', 'ask_folder', 'pending', '{"path":"D:/s","access":"read","why":"schemas"}', {
              outside_folder: 'D:/s',
            })}
            who="Lead"
            onDecide={vi.fn()}
          />
          <OutsideApproval
            call={toolCall('w', 'r', 'edit_file', 'pending', '{"path":"C:/m/b.md"}', { outside_folder: 'C:/m' })}
            who="Lead"
            onDecide={vi.fn()}
          />
          <OutsideApproval
            call={toolCall('g', 'r', 'ask_folder', 'pending', '{"path":"E:/t","access":"write","why":"output"}', {
              outside_folder: 'E:/t',
            })}
            who="Lead"
            onDecide={vi.fn()}
          />
          <MergeCard merge={kept} name="Coder" onDecide={vi.fn()} />
          <MergeCard merge={{ ...kept, id: 'h', status: 'pending', kept_in: null }} name="Tester" onDecide={vi.fn()} />
        </>,
      )
      // And nothing folded on these cards says what reaches further, is deleted, runs, is sent or spent.
      for (const fold of Array.from(document.querySelectorAll('.card-more-body')))
        expect(fold.textContent).not.toMatch(
          /every chat|from now on|asks again|delete|discard|runs?|sen[dt]s?|spen[dt]|pay|always/i,
        )
    },
    [
      /“Allow this site” lets every chat of this project open it without asking/,
      /“Always” is for GET to https:\/\/example\.com only: this scheme, host and port\./,
      /“Allow reading this folder” lets this conversation read there from now on/,
      /^Read only: a change there is asked about every time\. “Add to this chat”: no agent in this chat asks again/,
      /^Read and write: as in the project, at this chat’s permission level\. “Add to this chat”: no agent in this chat asks again/,
      /“Allow changes in this folder” lets this conversation work there from now on/,
      /Discard deletes that folder\./,
      /Tester made these in a working copy of its own\. Until you decide it holds these files/,
    ],
  ],
]

test.each(elsewhere)(
  '%s: its warnings are in sight, never behind ⓘ or in a closed fold',
  async (_page, show, warnings) => {
    await show()
    for (const warning of warnings) {
      const shown = screen.getByText(warning)
      expect(shown.closest('.hint')).toBeNull()
      expect(shown.closest('details:not([open])')).toBeNull()
    }
    cleanup()
  },
)
