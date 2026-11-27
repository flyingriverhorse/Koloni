import { useState } from 'react'
import type { Project } from '../../api/types'
import { useApp } from '../../state/store'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { OwnCommands } from '../OwnCommands'
import { useNewChats } from './NewChats'
import { fromOf, Legend, Marked, More, part, Row, Said } from './part'
import { agentsSaid } from './said'
import { USUAL } from './usual'

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

export const OPENING: [value: Project['spawn_approval'], label: string][] = [
  ['auto', 'Ask when it matters'],
  ['always', 'Always ask'],
  ['never', 'Never ask'],
]

/** The Scout at a turn's end (6 Nov): who it is and what it costs, in sight; the rest behind ⓘ. */
const SUGGEST_SHOWN =
  'The Scout looks for what is left after each turn that did something (changed a file, ran a command, handed work on or had a step fail): one small model request, on your plan or your bill; Usage shows it under that model. At Full auto the Orchestrator’s model decides them with one more.'
const SUGGEST_REST =
  'The first model of the tier you choose is sent what was said in the turn, the files it changed and the steps that failed, with the secrets KOLONİ knows masked, and the open tasks’ titles. It proposes at most three follow-up tasks, each from words of the turn; they wait on the To-do list for your Add, Edit or Reject. An added task runs once you tick it and give it to a chat (Do in chat). After a turn of a To-do story - one of its tasks’ or yours in its topic - they go into that story while it is open, one from a step that failed as a bug. Proposals made while you’re away always wait for you; discussions get none.'
const SUGGEST_TIERS: [value: Project['suggest_tier'], label: string][] = [
  ['fast', 'Fast tier'],
  ['balanced', 'Balanced tier'],
  ['strongest', 'Strongest tier'],
]

/**
 * This project › How agents work (0.1.10: Agents and New chats start with): who changes the files, the follow-up tasks
 * after a turn, the teams a new chat starts with; under More, a new chat's other folders and your slash commands.
 * `more`: asked open (Ctrl+K's "New chats start with" or "Slash commands"), each time with a new count.
 */
export function useAgents(project: Project, more?: number) {
  // (A server older than the page has no such field yet: a chat's default.)
  const savedWork = project.lead_work ?? 'delegates'
  const [leadWork, setLeadWork] = useState(savedWork)
  const [suggest, setSuggest] = useState(project.suggest_tasks)
  const [suggestTier, setSuggestTier] = useState(project.suggest_tier)
  const chats = useNewChats(project)
  const commands = useApp(s => s.ownCommands).length
  const patch = {
    ...(leadWork !== savedWork && { lead_work: leadWork }),
    ...(suggest !== project.suggest_tasks && { suggest_tasks: suggest }),
    ...(suggestTier !== project.suggest_tier && { suggest_tier: suggestTier }),
    ...chats.patch,
  }
  const now = { lead_work: leadWork, suggest_tasks: suggest, suggest_tier: suggestTier, teams_mode: chats.mode }
  return part(
    patch,
    true,
    <>
      <Said title="How agents work">{agentsSaid(now, chats.folders)}</Said>
      <p className="choice-note">Every chat of this project follows these, the ones made before too.</p>
      <Row
        label="Who changes the files"
        htmlFor="lead-work"
        doc={GUIDE.settingsAgents}
        why={LEAD_WORK.map(([, label, note]) => `${label}: ${note}`).join(' ')}
        from={fromOf(leadWork, savedWork, USUAL.lead_work)}
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
      <Marked from={fromOf(suggest, project.suggest_tasks, USUAL.suggest_tasks)}>
        <label className="choice">
          <input type="checkbox" checked={suggest} onChange={e => setSuggest(e.target.checked)} />
          <span>
            Suggest follow-up tasks after each turn
            <span className="choice-note">
              {SUGGEST_SHOWN} <Hint doc={GUIDE.todoProposals}>{SUGGEST_REST}</Hint>
            </span>
          </span>
        </label>
      </Marked>
      {suggest && (
        <Row
          label="Follow-up tasks from"
          htmlFor="suggest-tier"
          from={fromOf(suggestTier, project.suggest_tier, USUAL.suggest_tier)}
        >
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
      {chats.teams}
      <More count={2} set={Number(chats.folders > 0) + Number(commands > 0)} asked={more}>
        {chats.others}
        <OwnCommands projectId={project.id} />
      </More>
      <Legend />
    </>,
  )
}
