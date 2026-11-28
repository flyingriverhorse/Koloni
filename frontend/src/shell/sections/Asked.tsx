import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { ChatRules, JudgeOut, Project } from '../../api/types'
import { useJudgeMeasured } from '../../chat/judgeMeasured'
import { wordsMeasured } from '../../chat/levels'
import { ProjectRules } from '../../commands/ProjectRules'
import { ProjectSites } from '../../commands/Sites'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { OPENING, WHEN_AWAY } from './Agents'
import { useCommands, type Where } from './Commands'
import { fromOf, Legend, Marked, More, noSubmit, part, Row, Said, within } from './part'
import { askedMore, askedSaid } from './said'
import { USUAL } from './usual'

const AWAY_WHY =
  'Once a card has waited this many minutes - at once while you’re away (☾ Away on a chat’s line) - the Orchestrator picks, says why, and you see it under “Decided for you”: its agents’ questions, going on or stopping at a step limit. It opens a sub-agent on its role’s own model unless that model is at its limit, out of credit, or over this month’s budget; a move onto another model that may cost money, commands it may not run, deleting, reaching outside and Take in still wait.'
const OPENING_WHY =
  'Ask when it matters: only when you approve everything and the sub-agent could write files or run commands. Always: before every sub-agent. Never: sub-agents open on their own.'
/** §8: the judge's box for your words (Check what I said first, K-yargıç) - behind its ⓘ. */
const WORDS_WHY =
  'At Full auto a command that deletes, overwrites or sends something off this machine is put to the judge too: your preferences, this project’s rules as saved on the Memory page (not the folder’s .koloni/rules.md) and your own messages in this chat are read, and it runs without a card only when a line of yours names it; one a line of yours forbids is not run. Secret files, .koloni, files that steer later turns and paths outside the folder are always asked; anything that goes wrong opens the card as before. It works once your Judge model’s measurement has passed - none has yet - or in a project where Check what I said first was on before 0.1.9.'

/** Full auto's judge (0.1.9): what it does and costs, in sight under its box; the rest behind ⓘ. */
const JUDGE_SHOWN =
  'A small model looks at each command the list does not stop. One request of your Judge model (Settings › The app › Agents) for each such command, on your plan or your bill.'
const JUDGE_REST =
  'At Full auto - in a chat you watch, a To-do task’s turn in a chat and a job while you’re away - a command the list does not stop is sent to the model first, with your words: one it finds risky is refused, or waits for you on a card, as you choose below. Reads, ordinary work (tests, compilers and checkers, local git), and your own test command (unless it runs a program an agent wrote) are not asked about. One it cannot get an answer for - no model to ask among them - waits for you on a card, whichever you choose, and the chat says why. Off: Full auto as before.'
/** What the judge does with a command it finds risky (25 Nov): refused, as Claude Code's auto mode does, or a card. */
const JUDGE_RISKY: [value: Project['judge_risky'], label: string][] = [
  ['refuse', 'Refuse and go on'],
  ['ask', 'Ask me'],
]
const RISKY_WHY =
  'Refuse and go on: the command does not run - its agent is told a general reason (never the judge’s sentence, which may quote your messages) and goes on another way, with no card and nothing waiting; the command’s row and Decided for you show you the sentence. After 3 refusals in a row (a command that ran ends a row) or 20 in a turn, each risky one waits for you on a card for the rest of the turn. Ask me: it waits for you on a card, “KOLONİ’s judge: …”. In a job while you’re away it is always parked for you, and a card the judge could not answer for (no answer in time, none it could read, no room to ask) waits at either.'

/** What a link or Ctrl+K asked of the section, each time with a new count: the rules shown, or More open. */
export type AskedFor = { what: 'rules' | 'more'; n: number }

/**
 * This project › When you’re asked (0.1.10: Asking and away, Runs without asking, and Commands and secrets): Full auto’s
 * judge and what runs without asking; who answers while you are away and when a sub-agent asks; under More, the
 * deletes KOLONİ checks, where commands run and what of your secrets they see. Its Save sends what changed - and,
 * where anything of the commands changed, where they run, whole, as the Commands section’s Save did.
 */
export function useAsking(project: Project, where: Where, chat?: { id: string; title: string }, asked?: AskedFor) {
  const judge = useFullAutoJudge(project)
  const noJudge = useNoJudge()
  const away = useAway(project)
  const opening = useOpening(project)
  const disposable = useDisposableDeletes(project)
  const commands = useCommands(project, where)
  const patch = {
    ...judge.patch,
    ...away.patch,
    ...opening.patch,
    ...disposable.patch,
    ...(commands.changed && commands.patch),
  }
  return part(
    patch,
    away.valid && commands.valid,
    <>
      <Said title="When you’re asked">
        {askedSaid({
          ...judge.now,
          ...away.now,
          ...opening.now,
          no_judge: noJudge,
          folded: askedMore({ ...disposable.now, ...commands.now }),
        })}
      </Said>
      <h3>Commands</h3>
      {judge.row}
      <Rules projectId={project.id} chat={chat} asked={asked?.what === 'rules' ? asked.n : undefined} />
      <h3>While you’re away</h3>
      {away.row}
      {opening.row}
      <More
        count={6}
        set={askedMore(saved(project))}
        bad={!commands.valid}
        asked={asked?.what === 'more' ? asked.n : undefined}
      >
        {disposable.row}
        {commands.view}
      </More>
      <Legend />
    </>,
    { take: commands.take },
  )
}

/** `useAsking`'s row for while you are away: who answers a card that waits, and after how long. */
function useAway(project: Project) {
  const savedAway = project.when_away ?? 'waits'
  const savedMinutes = project.away_minutes ?? 5
  const [whenAway, setWhenAway] = useState(savedAway)
  const [minutesText, setMinutesText] = useState(String(savedMinutes))
  const awayMinutes = within(minutesText, 0, 1440)
  const awayFrom = fromOf(
    [whenAway, minutesText.trim()],
    [savedAway, String(savedMinutes)],
    [USUAL.when_away, String(USUAL.away_minutes)],
  )
  return {
    patch: {
      ...(whenAway !== savedAway && { when_away: whenAway }),
      ...(awayMinutes !== undefined && awayMinutes !== savedMinutes && { away_minutes: awayMinutes }),
    },
    valid: awayMinutes !== undefined,
    now: { when_away: whenAway, away_minutes: awayMinutes ?? savedMinutes },
    row: (
      <Row
        label="When you’re away"
        htmlFor="when-away"
        doc={GUIDE.answeringForYou}
        why={AWAY_WHY}
        from={awayFrom}
        warn={
          <>
            {awayMinutes === undefined && <span className="choice-note">0 (at once) to 1440 minutes.</span>}
            {whenAway === 'lead' && (
              <span className="choice-note">
                An Orchestrator on a CLI uses one request of your plan for each answer.
              </span>
            )}
          </>
        }
      >
        <select
          id="when-away"
          className="input"
          value={whenAway}
          onChange={e => setWhenAway(e.target.value as Project['when_away'])}
        >
          {WHEN_AWAY.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>{' '}
        <span className="set-inline">
          after{' '}
          <input
            id="away-minutes"
            className="input mono set-short"
            inputMode="numeric"
            aria-label="Minutes before the Orchestrator answers"
            value={minutesText}
            aria-invalid={awayMinutes === undefined || undefined}
            onChange={e => setMinutesText(e.target.value)}
          />{' '}
          min
        </span>
      </Row>
    ),
  }
}

/** `useAsking`'s row for when a sub-agent asks before it opens. */
function useOpening(project: Project) {
  const savedApproval = project.spawn_approval ?? 'auto'
  const [approval, setApproval] = useState(savedApproval)
  return {
    patch: approval !== savedApproval ? { spawn_approval: approval } : {},
    now: { spawn_approval: approval },
    row: (
      <Row
        label="Opening a sub-agent"
        htmlFor="spawn-approval"
        doc={GUIDE.settingsAsking}
        why={OPENING_WHY}
        from={fromOf(approval, savedApproval, USUAL.spawn_approval)}
        warn={
          approval === 'never' && (
            <span className="choice-note">Sub-agents open on their own, in every chat of this project.</span>
          )
        }
      >
        <select
          id="spawn-approval"
          className="input"
          value={approval}
          onChange={e => setApproval(e.target.value as Project['spawn_approval'])}
        >
          {OPENING.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Row>
    ),
  }
}

/** Whether no model can be asked for Full auto's judge now (`/api/judge`'s `now` null): its sentence says so then. */
function useNoJudge() {
  const [none, setNone] = useState(false)
  useEffect(() => {
    let live = true
    api.get<JudgeOut>('/judge').then(
      judge => live && setNone(judge?.now === null),
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [])
  return none
}

/** `useAsking`'s switch for Full auto's judge (0.1.9), on unless turned off; what it costs in sight, the rest behind ⓘ -
 *  under it what it does with a command it finds risky (refused unless you say Ask me; not while it is off), and its box
 *  for your words (§8), which may be ticked only once measured, and always unticked. */
function useFullAutoJudge(project: Project) {
  const [on, setOn] = useState(project.full_auto_judge)
  const [words, setWords] = useState(project.judge_words)
  const [risky, setRisky] = useState(project.judge_risky)
  const measured = useJudgeMeasured(!wordsMeasured(project)) || wordsMeasured(project)
  const locked = !measured && !words
  return {
    patch: {
      ...(on !== project.full_auto_judge && { full_auto_judge: on }),
      ...(words !== project.judge_words && { judge_words: words }),
      ...(risky !== project.judge_risky && { judge_risky: risky }),
    },
    // (Its box for your words does nothing until its measurement has passed: the sentence says what is so.)
    now: { full_auto_judge: on, judge_words: words && measured, judge_risky: risky },
    row: (
      <>
        <Marked from={fromOf(on, project.full_auto_judge, USUAL.full_auto_judge)}>
          <label className="choice">
            <input type="checkbox" checked={on} onChange={e => setOn(e.target.checked)} />
            <span>
              Full auto’s judge
              <span className="choice-note">
                {JUDGE_SHOWN} <Hint doc={GUIDE.fullAutoJudge}>{JUDGE_REST}</Hint>
              </span>
            </span>
          </label>
        </Marked>
        <div className="set-sub">
          <Row
            label="When the judge finds a command risky"
            htmlFor="judge-risky"
            doc={GUIDE.fullAutoJudge}
            why={RISKY_WHY}
            from={fromOf(risky, project.judge_risky, USUAL.judge_risky)}
          >
            <select
              id="judge-risky"
              className="input"
              value={risky}
              disabled={!on}
              onChange={e => setRisky(e.target.value as Project['judge_risky'])}
            >
              {JUDGE_RISKY.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Row>
          <Marked from={fromOf(words, project.judge_words, USUAL.judge_words)}>
            <label className={`choice${locked ? ' choice-disabled' : ''}`}>
              <input type="checkbox" checked={words} disabled={locked} onChange={e => setWords(e.target.checked)} />
              <span>
                It also lets a delete or a push run when a line you saved names it
                {measured ? '' : ' (after its measurement)'} <Hint doc={GUIDE.checkWhatISaid}>{WORDS_WHY}</Hint>
              </span>
            </label>
          </Marked>
        </div>
      </>
    ),
  }
}

/** `useAsking`'s switch for what KOLONİ checks is disposable (coordination §4): such a delete goes without a card where it is on. */
function useDisposableDeletes(project: Project) {
  const [allowed, setAllowed] = useState(project.disposable_deletes)
  return {
    patch: allowed === project.disposable_deletes ? {} : { disposable_deletes: allowed },
    now: { disposable_deletes: allowed },
    row: (
      <Marked from={fromOf(allowed, project.disposable_deletes, USUAL.disposable_deletes)}>
        <label className="choice">
          <input type="checkbox" checked={allowed} onChange={e => setAllowed(e.target.checked)} />
          <span>
            Agents may delete what is disposable without asking
            <span className="choice-note">
              (clean worktrees and merged branches you no longer use, build and cache folders) - at Auto-edit and Full
              auto, in a chat you watch. KOLONİ checks each one first; any other delete asks as before.
            </span>
          </span>
        </label>
      </Marked>
    ),
  }
}

/**
 * Runs without asking, as a row (0.1.10): what it is, and the project's sites and each chat's commands and requests a
 * click away, read once shown (a host half typed there goes when they are hidden, as it went with another section
 * chosen). Each is removed there at once, not by Save.
 * `asked`: shown (a chat's "run without asking" link), each time with a new count.
 */
function Rules({
  projectId,
  chat,
  asked,
}: {
  projectId: string
  chat?: { id: string; title: string }
  asked?: number
}) {
  // The project's sites, counted into each chat's "run without asking" as the chat's own link counts them.
  const [siteCount, setSiteCount] = useState(0)
  const [open, setOpen] = useState(asked !== undefined)
  const [seen, setSeen] = useState(asked)
  if (asked !== seen) {
    setSeen(asked)
    if (asked !== undefined) setOpen(true)
  }
  const rules = useRuleCount(projectId, open)
  return (
    <>
      {/* (No cell: a list of its own, each removed at once - its place keeps the row in line with those that have one.) */}
      <Row
        label="Runs without asking"
        from={null}
        warn={
          <span className="choice-note">
            {rules !== null && `${rules} rule${rules === 1 ? '' : 's'}: `}The project’s sites, for every chat, and each
            chat’s own “Always run” commands and requests: each is removed there at once.
          </span>
        }
      >
        <button
          type="button"
          className="btn btn-small"
          aria-expanded={open}
          aria-controls={open ? 'rules-without-asking' : undefined}
          onClick={() => setOpen(!open)}
        >
          {open ? 'Hide the rules' : 'Show the rules'}
        </button>
      </Row>
      {open && (
        // (Saved rule by rule: Enter in a field or on a box of theirs sends nothing of the section's Save. No control of
        // its own - its fields' Enter stops here on its way to the form.)
        <div id="rules-without-asking" role="presentation" className="set-rules" onKeyDown={noSubmit}>
          <ProjectSites projectId={projectId} onCount={setSiteCount} />
          <ProjectRules projectId={projectId} chat={chat} sites={siteCount} />
        </div>
      )}
    </>
  )
}

/** What of More a project has saved, its fields' defaults where an older server leaves one out. */
const saved = (project: Project) => ({
  disposable_deletes: project.disposable_deletes,
  exec_location: project.exec_location,
  docker_network: project.docker_network,
  longest_command: project.longest_command ?? USUAL.longest_command,
  hide_secrets: project.hide_secrets ?? USUAL.hide_secrets,
  pass_env: project.pass_env ?? null,
  canary: project.canary ?? USUAL.canary,
})

/**
 * How many rules run without asking here - the project's sites and each chat's commands and requests - read without
 * opening them, and again each time they are shown or hidden (a rule removed there). null until read.
 */
function useRuleCount(projectId: string, open: boolean) {
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let live = true
    Promise.all([
      api.get<unknown[]>(`/projects/${projectId}/sites`),
      api.get<ChatRules[]>(`/projects/${projectId}/allowed`),
    ]).then(
      ([sites, chats]) =>
        live &&
        Array.isArray(sites) &&
        Array.isArray(chats) &&
        setCount(sites.length + chats.reduce((sum, one) => sum + one.commands.length + one.web.length, 0)),
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [projectId, open])
  return count
}
