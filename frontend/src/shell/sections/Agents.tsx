import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { part, Row, within } from './part'

/** Who changes the files (K-devret): every chat's choice, the project's (tek-ev); and the To-do page's for its chats. */
export const LEAD_WORK: [value: Project['lead_work'], label: string, note: string][] = [
  ['delegates', 'Orchestrator delegates the work', 'The Orchestrator plans, asks and checks; sub-agents change the files.'],
  ['decides', 'Orchestrator decides', 'A small change (one or two files, a few lines) it makes itself, asking as usual; bigger work goes to a sub-agent.'],
  ['itself', 'Orchestrator does it itself', 'It changes the files itself, and may still hand a part to a sub-agent.'],
]

/** While you're away (K-vekil-karar): what waits for you, and what the Orchestrator may answer. */
export const WHEN_AWAY: [value: Project['when_away'], label: string][] = [
  ['waits', 'Everything waits for you'],
  ['lead', 'The Orchestrator answers what it safely can'],
]
const AWAY_WHY =
  'Questions and decisions wait until you’re back - or, once you haven’t answered for so many minutes or the away card is on, the Orchestrator picks, says why, and you see it under “Decided for you”. It opens a sub-agent on its role’s own model unless that model is at its limit, out of credit, or over this month’s budget; a move onto another model that may cost money, commands it may not run, deleting, reaching outside and Take in still wait.'

export const OPENING: [value: Project['spawn_approval'], label: string][] = [
  ['auto', 'Ask when it matters'],
  ['always', 'Always ask'],
  ['never', 'Never ask'],
]
const OPENING_WHY = 'Ask when it matters: only when you approve everything and the sub-agent could write files or run commands. Always: before every sub-agent. Never: sub-agents open on their own.'

/** What a look over each report costs, and what is sent to which model, in sight under its box; the rest behind ⓘ. */
const OBSERVE_SHOWN =
  'One more model request after every sub-agent’s report, on your plan or your bill; Usage shows it under that model. The Observer role’s model (set on the Agents page) is sent the task, the report, the diffs of the changed files and the test’s output, with the secrets KOLONİ knows masked.'
const OBSERVE_REST = 'It says, with no tools, what of the report the record shows. The Orchestrator takes its words as an opinion, not a fact.'

/** The Assistant PO at a turn's end (6 Nov): what it costs, in sight; the rest behind ⓘ. */
const SUGGEST_SHOWN =
  'One small model request after each turn that did something (changed a file, ran a command, handed work on or had a step fail), on your plan or your bill; Usage shows it under that model. At Full auto the Orchestrator’s model decides them with one more.'
const SUGGEST_REST =
  'The first model of the tier you choose is sent what was said in the turn, the files it changed and the steps that failed, with the secrets KOLONİ knows masked, and the open tasks’ titles. It proposes at most three follow-up tasks, each from words of the turn; they wait on the To-do list for your Add, Edit or Reject. An added task starts when you run the backlog, or by itself where the To-do list runs by itself. Proposals made while you’re away or by a trigger always wait for you; rooms, discussions and To-do tasks’ own turns get none.'
const SUGGEST_TIERS: [value: Project['suggest_tier'], label: string][] = [
  ['fast', 'Fast tier'],
  ['balanced', 'Balanced tier'],
  ['strongest', 'Strongest tier'],
]

/** 89m: whether its agents finish only when the tests pass - as the user set it, else as it is by itself. */
const finishing = (project: Project) => project.finish_tests ?? project.finish_tests_auto?.on ?? false

/** Why, under the switch: what it is by itself, and why. */
function finishNote(project: Project): string {
  const auto = project.finish_tests_auto
  if (!auto) return ''
  const by = `${auto.on ? 'on' : 'off'}: ${auto.reason}.`
  return project.finish_tests == null ? `By default ${by}` : `You set this; by default it would be ${by}`
}

/** This project › Agents: who changes the files, and what is checked of their work. */
export function useAgents(project: Project) {
  // (A server older than the page has no such field yet: a chat's default.)
  const savedWork = project.lead_work ?? 'delegates'
  const [leadWork, setLeadWork] = useState(savedWork)
  const [finishTests, setFinishTests] = useState(finishing(project))
  const [observe, setObserve] = useState(project.observe_reports)
  const [suggest, setSuggest] = useState(project.suggest_tasks)
  const [suggestTier, setSuggestTier] = useState(project.suggest_tier)
  const patch = {
    ...(leadWork !== savedWork && { lead_work: leadWork }),
    // (Chosen as it would be by itself: automatic again, so that it follows the tests' time.)
    ...(finishTests !== finishing(project) && { finish_tests: finishTests === project.finish_tests_auto?.on ? null : finishTests }),
    ...(observe !== project.observe_reports && { observe_reports: observe }),
    ...(suggest !== project.suggest_tasks && { suggest_tasks: suggest }),
    ...(suggestTier !== project.suggest_tier && { suggest_tier: suggestTier }),
  }
  return part(
    patch,
    true,
    <>
      <h2>Agents</h2>
      <p className="choice-note">Every chat of this project follows these, the ones made before too.</p>
      <Row label="Who changes the files" htmlFor="lead-work" doc={GUIDE.settingsAgents} why={LEAD_WORK.map(([, label, note]) => `${label}: ${note}`).join(' ')}>
        <select id="lead-work" className="input" value={leadWork} onChange={e => setLeadWork(e.target.value as Project['lead_work'])}>
          {LEAD_WORK.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Row>
      <label className="choice">
        <input type="checkbox" checked={finishTests} onChange={e => setFinishTests(e.target.checked)} />
        <span>
          Finish only when the tests pass
          <span className="choice-note">
            An agent (the Orchestrator or a sub-agent) on Claude Code that changed files is sent back to work, at most twice, while
            {project.finish_tests_auto?.command ? <> <code>{project.finish_tests_auto.command}</code> fails.</> : ' the tests fail.'}{' '}
            KOLONİ runs them where this project’s commands run, by itself only in Full auto or under an Always run rule.
          </span>
          <span className="choice-note" data-testid="finish-tests-why">{finishNote(project)}</span>
        </span>
      </label>
      <label className="choice">
        {/* Named by all of its note, as the commit box is: a browser leaves a closed hint out of a name. */}
        <input type="checkbox" aria-label={`Have a model look over each sub-agent’s report ${OBSERVE_SHOWN} ${OBSERVE_REST}`} checked={observe} onChange={e => setObserve(e.target.checked)} />
        <span>
          Have a model look over each sub-agent’s report
          <span className="choice-note">
            {OBSERVE_SHOWN} <Hint doc={GUIDE.observer}>{OBSERVE_REST}</Hint>
          </span>
        </span>
      </label>
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
          <select id="suggest-tier" className="input" value={suggestTier} onChange={e => setSuggestTier(e.target.value as Project['suggest_tier'])}>
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
  const savedMinutes = project.away_minutes ?? 10
  const savedApproval = project.spawn_approval ?? 'auto'
  const [whenAway, setWhenAway] = useState(savedAway)
  const [minutesText, setMinutesText] = useState(String(savedMinutes))
  const awayMinutes = within(minutesText, 0, 1440)
  const [approval, setApproval] = useState(savedApproval)
  const patch = {
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
        doc={GUIDE.settingsAsking} why={OPENING_WHY}
        warn={approval === 'never' && <span className="choice-note">Sub-agents open on their own, in every chat of this project.</span>}
      >
        <select id="spawn-approval" className="input" value={approval} onChange={e => setApproval(e.target.value as Project['spawn_approval'])}>
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
        doc={GUIDE.answeringForYou} why={AWAY_WHY}
        warn={
          <>
            {awayMinutes === undefined && <span className="choice-note">0 (at once) to 1440 minutes.</span>}
            {whenAway === 'lead' && <span className="choice-note">An Orchestrator on a CLI uses one request of your plan for each answer.</span>}
          </>
        }
      >
        <select id="when-away" className="input" value={whenAway} onChange={e => setWhenAway(e.target.value as Project['when_away'])}>
          {WHEN_AWAY.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>{' '}
        <span className="set-inline">
          after{' '}
          <input id="away-minutes" className="input mono set-short" inputMode="numeric" aria-label="Minutes before the Orchestrator answers" value={minutesText} aria-invalid={awayMinutes === undefined || undefined} onChange={e => setMinutesText(e.target.value)} />{' '}
          min
        </span>
      </Row>
    </>,
  )
}
