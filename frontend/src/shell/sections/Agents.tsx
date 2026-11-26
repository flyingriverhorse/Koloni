import { useState } from 'react'
import type { Project } from '../../api/types'
import { useJudgeMeasured } from '../../chat/judgeMeasured'
import { wordsMeasured } from '../../chat/levels'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { part, Row, within } from './part'

/** Who changes the files (K-devret): every chat's choice, the project's (tek-ev); and the To-do page's for its chats. */
export const LEAD_WORK: [value: Project['lead_work'], label: string, note: string][] = [
  [
    'delegates',
    'Orchestrator delegates the work',
    'The Orchestrator plans, asks and checks; sub-agents change the files.',
  ],
  [
    'decides',
    'Orchestrator decides',
    'A small change (one or two files, a few lines) it makes itself, asking as usual; bigger work goes to a sub-agent.',
  ],
  ['itself', 'Orchestrator does it itself', 'It changes the files itself, and may still hand a part to a sub-agent.'],
]

/** While you're away (K-vekil-karar): what waits for you, and what the Orchestrator may answer. */
export const WHEN_AWAY: [value: Project['when_away'], label: string][] = [
  ['waits', 'Everything waits for you'],
  ['lead', 'The Orchestrator answers what it safely can'],
]
const AWAY_WHY =
  'Once a card has waited this many minutes - at once while you’re away (☾ Away on a chat’s line) - the Orchestrator picks, says why, and you see it under “Decided for you”: its agents’ questions, going on or stopping at a step limit. It opens a sub-agent on its role’s own model unless that model is at its limit, out of credit, or over this month’s budget; a move onto another model that may cost money, commands it may not run, deleting, reaching outside and Take in still wait.'

export const OPENING: [value: Project['spawn_approval'], label: string][] = [
  ['auto', 'Ask when it matters'],
  ['always', 'Always ask'],
  ['never', 'Never ask'],
]
const OPENING_WHY =
  'Ask when it matters: only when you approve everything and the sub-agent could write files or run commands. Always: before every sub-agent. Never: sub-agents open on their own.'

/** §8: the judge's box for your words (Check what I said first, K-yargıç) - behind its ⓘ. */
const WORDS_WHY =
  'At Full auto a command that deletes, overwrites or sends something off this machine is put to the judge too: your preferences, this project’s rules as saved on the Memory page (not the folder’s .koloni/rules.md) and your own messages in this chat are read, and it runs without a card only when a line of yours names it; one a line of yours forbids is not run. Secret files, .koloni, files that steer later turns and paths outside the folder are always asked; anything that goes wrong opens the card as before. It works once your Judge model’s measurement has passed - none has yet - or in a project where Check what I said first was on before 0.1.9.'

/** Full auto's judge (0.1.9): what it does and costs, in sight under its box; the rest behind ⓘ. */
const JUDGE_SHOWN =
  'A small model looks at each command the list does not stop. One request of your Judge model (Settings › The app › Agents) for each such command, on your plan or your bill.'
const JUDGE_REST =
  'At Full auto - in a chat you watch, a To-do task’s turn in a chat and a job while you’re away - a command the list does not stop is sent to the model first, with your words: one it finds risky is refused, or waits for you on a card, as you choose below. Reads, ordinary work (tests, compilers and checkers, local git), your own test command (unless it runs a program an agent wrote) and a trigger’s turn are not asked about. One it cannot get an answer for waits for you on a card, whichever you choose; only where there is no model to ask does it stand aside for the turn, and it says so in the chat. Off: Full auto as before.'
/** What the judge does with a command it finds risky (25 Nov): refused, as Claude Code's auto mode does, or a card. */
const JUDGE_RISKY: [value: Project['judge_risky'], label: string][] = [
  ['refuse', 'Refuse and go on'],
  ['ask', 'Ask me'],
]
const RISKY_WHY =
  'Refuse and go on: the command does not run - its agent is told a general reason (never the judge’s sentence, which may quote your messages) and goes on another way, with no card and nothing waiting; the command’s row and Decided for you show you the sentence. After 3 refusals in a turn the next risky one waits for you on a card. Ask me: it waits for you on a card, “KOLONİ’s judge: …”. In a job while you’re away it is always parked for you, and a card the judge could not answer for (no answer in time, none it could read, no room to ask) waits at either.'

/** The Scout at a turn's end (6 Nov): who it is and what it costs, in sight; the rest behind ⓘ. */
const SUGGEST_SHOWN =
  'The Scout looks for what is left after each turn that did something (changed a file, ran a command, handed work on or had a step fail): one small model request, on your plan or your bill; Usage shows it under that model. At Full auto the Orchestrator’s model decides them with one more.'
const SUGGEST_REST =
  'The first model of the tier you choose is sent what was said in the turn, the files it changed and the steps that failed, with the secrets KOLONİ knows masked, and the open tasks’ titles. It proposes at most three follow-up tasks, each from words of the turn; they wait on the To-do list for your Add, Edit or Reject. An added task runs once you tick it and give it to a chat (Do in chat). After a turn of a To-do story - one of its tasks’ or yours in its topic - they go into that story while it is open, one from a step that failed as a bug. Proposals made while you’re away or by a trigger always wait for you; rooms and discussions get none.'
const SUGGEST_TIERS: [value: Project['suggest_tier'], label: string][] = [
  ['fast', 'Fast tier'],
  ['balanced', 'Balanced tier'],
  ['strongest', 'Strongest tier'],
]

/** This project › Agents: who changes the files, and what is checked of their work. */
export function useAgents(project: Project) {
  // (A server older than the page has no such field yet: a chat's default.)
  const savedWork = project.lead_work ?? 'delegates'
  const [leadWork, setLeadWork] = useState(savedWork)
  const [suggest, setSuggest] = useState(project.suggest_tasks)
  const [suggestTier, setSuggestTier] = useState(project.suggest_tier)
  const patch = {
    ...(leadWork !== savedWork && { lead_work: leadWork }),
    ...(suggest !== project.suggest_tasks && { suggest_tasks: suggest }),
    ...(suggestTier !== project.suggest_tier && { suggest_tier: suggestTier }),
  }
  return part(
    patch,
    true,
    <>
      <h2>Agents</h2>
      <p className="choice-note">Every chat of this project follows these, the ones made before too.</p>
      <Row
        label="Who changes the files"
        htmlFor="lead-work"
        doc={GUIDE.settingsAgents}
        why={LEAD_WORK.map(([, label, note]) => `${label}: ${note}`).join(' ')}
      >
        <select
          id="lead-work"
          className="input"
          value={leadWork}
          onChange={e => setLeadWork(e.target.value as Project['lead_work'])}
        >
          {LEAD_WORK.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Row>
      <label className="choice">
        <input type="checkbox" checked={suggest} onChange={e => setSuggest(e.target.checked)} />
        <span>
          Suggest follow-up tasks after each turn
          <span className="choice-note">
            {SUGGEST_SHOWN} <Hint doc={GUIDE.todoProposals}>{SUGGEST_REST}</Hint>
          </span>
        </span>
      </label>
      {suggest && (
        <Row label="Follow-up tasks from" htmlFor="suggest-tier">
          <select
            id="suggest-tier"
            className="input"
            value={suggestTier}
            onChange={e => setSuggestTier(e.target.value as Project['suggest_tier'])}
          >
            {SUGGEST_TIERS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Row>
      )}
    </>,
  )
}

/** This project › Asking and away: when a sub-agent is asked for, and who answers while you are away. */
export function useAsking(project: Project) {
  const savedAway = project.when_away ?? 'waits'
  const savedMinutes = project.away_minutes ?? 5
  const savedApproval = project.spawn_approval ?? 'auto'
  const [whenAway, setWhenAway] = useState(savedAway)
  const [minutesText, setMinutesText] = useState(String(savedMinutes))
  const awayMinutes = within(minutesText, 0, 1440)
  const [approval, setApproval] = useState(savedApproval)
  const judge = useFullAutoJudge(project)
  const disposable = useDisposableDeletes(project)
  const patch = {
    ...judge.patch,
    ...disposable.patch,
    ...(approval !== savedApproval && { spawn_approval: approval }),
    ...(whenAway !== savedAway && { when_away: whenAway }),
    ...(awayMinutes !== undefined && awayMinutes !== savedMinutes && { away_minutes: awayMinutes }),
  }
  return part(
    patch,
    awayMinutes !== undefined,
    <>
      <h2>Asking and away</h2>
      <Row
        label="Opening a sub-agent"
        htmlFor="spawn-approval"
        doc={GUIDE.settingsAsking}
        why={OPENING_WHY}
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
      <Row
        label="When you’re away"
        htmlFor="when-away"
        doc={GUIDE.answeringForYou}
        why={AWAY_WHY}
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
      {judge.row}
      {disposable.row}
    </>,
  )
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
    row: (
      <>
        <label className="choice">
          <input type="checkbox" checked={on} onChange={e => setOn(e.target.checked)} />
          <span>
            Full auto’s judge
            <span className="choice-note">
              {JUDGE_SHOWN} <Hint doc={GUIDE.fullAutoJudge}>{JUDGE_REST}</Hint>
            </span>
          </span>
        </label>
        <Row
          label="When the judge finds a command risky"
          htmlFor="judge-risky"
          doc={GUIDE.fullAutoJudge}
          why={RISKY_WHY}
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
        <label className={`choice${locked ? ' choice-disabled' : ''}`}>
          <input type="checkbox" checked={words} disabled={locked} onChange={e => setWords(e.target.checked)} />
          <span>
            It also lets a delete or a push run when a line you saved names it
            {measured ? '' : ' (after its measurement)'} <Hint doc={GUIDE.checkWhatISaid}>{WORDS_WHY}</Hint>
          </span>
        </label>
      </>
    ),
  }
}

/** `useAsking`'s switch for what KOLONİ checks is disposable (coordination §4): such a delete goes without a card where it is on. */
function useDisposableDeletes(project: Project) {
  const [allowed, setAllowed] = useState(project.disposable_deletes)
  return {
    patch: allowed === project.disposable_deletes ? {} : { disposable_deletes: allowed },
    row: (
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
    ),
  }
}
