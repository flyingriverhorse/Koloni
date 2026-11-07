import { useState } from 'react'
import type { PendingSkill, SkillFound, SkillPreview } from '../api/types'
import { Seen } from '../tools/PackageLook'
import { DecisionCard, type SpawnDecision } from './SpawnApproval'

/** A size in bytes the way a person reads it. */
const sizeText = (bytes: number) =>
  bytes < 1024 ? `${bytes} bytes` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1024 / 1024).toFixed(1)} MiB`

/** Its licence's first line - or, without one, that nobody knows on what terms it may be used. */
export function Licence({ skill }: { skill: Pick<SkillFound, 'license'> }) {
  return skill.license ? <span className="tag mono">{skill.license}</span> : <span className="tag tag-warn">licence unknown</span>
}

/** Its SKILL.md, folded, with the files beside it. */
export function SkillText({ skill }: { skill: SkillFound }) {
  return (
    <details className="more">
      <summary>Show SKILL.md</summary>
      <pre className="cmd-approval-command spawn-task">{skill.text}</pre>
      <div className="muted cmd-approval-note">
        {skill.files.length} files, {sizeText(skill.size)}: <span className="mono">{skill.files.join(', ')}</span>
      </div>
    </details>
  )
}

/** Whether its scripts run without asking: the user's word, given as the skill is added (on unless taken away). Before it is added, each script is there to be read. */
export function ScriptsLeave({
  id,
  skill,
  texts,
  checked,
  onChange,
}: {
  id: string
  skill: SkillFound
  texts?: Record<string, string>
  checked: boolean
  onChange: (on: boolean) => void
}) {
  if (skill.scripts.length === 0) return <div className="muted cmd-approval-note">It has no scripts.</div>
  return (
    <>
      <div className="muted cmd-approval-note">
        Its scripts: <span className="mono">{skill.scripts.join(', ')}</span>
      </div>
      {texts &&
        skill.scripts.map(script => (
          <details key={script} className="more">
            <summary>Show {script}</summary>
            <pre className="cmd-approval-command spawn-task">{texts[script]}</pre>
          </details>
        ))}
      <label className="choice" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          aria-label={`Run the scripts of ${skill.name} without asking`}
          aria-describedby={`${id}-note`}
          checked={checked}
          onChange={e => onChange(e.target.checked)}
        />
        <span>
          Run the scripts of {skill.name} without asking
          <span id={`${id}-note`} className="choice-note">
            Saying yes to this is agreeing to run them. Any other command is asked about as before, and once a file of the
            skill has changed since it was added its scripts are asked about too.
          </span>
        </span>
      </label>
    </>
  )
}

/** A skill as it is shown before it is added: where from, what it holds, and what of it is not copied. */
export function SkillShown({ skill }: { skill: SkillPreview }) {
  return (
    <>
      <div className="cmd-approval-where">
        <strong>{skill.name}</strong>
        <Licence skill={skill} />
      </div>
      {skill.description && <div className="spawn-line">{skill.description}</div>}
      <div className="muted cmd-approval-note">
        From <span className="mono">{skill.source}</span>: {skill.files.length} files, {sizeText(skill.size)}.
      </div>
      {skill.injection_rules && skill.injection_rules.length > 0 && (
        <div role="note" className="cmd-approval-note">
          Its SKILL.md has phrases that try to steer an agent past you (rules: {skill.injection_rules.map(rule => rule.replaceAll('_', ' ')).join(', ')}). Read it
          before you add it.
        </div>
      )}
      {!skill.license && (
        <div className="muted cmd-approval-note">It has no licence: on what terms it may be used is not known.</div>
      )}
      {skill.skipped.length > 0 && (
        <div className="muted cmd-approval-note">
          Not copied: <span className="mono">{skill.skipped.join(', ')}</span>
        </div>
      )}
      {/* Slice 92: what it holds, may use and would run, in sight before the yes. */}
      <div className="muted cmd-approval-note">
        Its files: <span className="mono">{skill.files.join(', ')}</span>
      </div>
      {skill.programs.length > 0 && (
        <div className="cmd-approval-note">
          Files that run as programs: <span className="mono">{skill.programs.join(', ')}</span>. KOLONİ does not run them as
          its scripts; an agent’s command that runs one is held to the rules of any command.
        </div>
      )}
      {!skill.read_whole && (
        <div className="muted cmd-approval-note">
          From GitHub only its SKILL.md, licence and scripts are read before you say yes: a #! line in another file is not
          seen here.
        </div>
      )}
      <div className="muted cmd-approval-note">
        {skill.allowed_tools.length > 0 ? (
          <>
            It declares allowed-tools: <span className="mono">{skill.allowed_tools.join(', ')}</span>. KOLONİ gives a skill
            none of them: its agents keep their role’s tools, and Claude Code is given it without that line.
          </>
        ) : (
          'It declares no allowed-tools.'
        )}
      </div>
      {skill.runs_as_it_loads.length > 0 && (
        <div className="cmd-approval-note">
          Lines Claude Code would run as the skill loads (!`…`), past every card:
          <pre className="cmd-approval-command">{skill.runs_as_it_loads.join('\n')}</pre>
          So it is not given to Claude Code as a skill of its own; other agents read these lines as text.
        </div>
      )}
      {skill.shell_blocks > 0 && (
        <div className="cmd-approval-note">
          Its SKILL.md has {skill.shell_blocks === 1 ? 'a shell block' : `${skill.shell_blocks} shell blocks`}: commands it
          tells an agent to run, each held to the rules of any command.
        </div>
      )}
      {skill.scripts.length > 0 && (
        <Seen
          seen={skill.seen}
          notSeen={['What its SKILL.md tells an agent to do: read it below.', 'Paths, addresses and programs put together while its scripts run.']}
        />
      )}
      <SkillText skill={skill} />
    </>
  )
}

interface Props {
  skill: PendingSkill
  /** Yes with `ask_scripts`: added, without leave for its scripts. */
  onDecide: (decision: SpawnDecision, scope?: 'ask_scripts') => Promise<void>
}

/** Asks before a skill an agent proposed is added: its text, files, size, licence, scripts and the roles it goes to. */
export function SkillApproval({ skill, onDecide }: Props) {
  const [unasked, setUnasked] = useState(true)
  return (
    <DecisionCard
      kicker="Add this skill?"
      approve="Add skill"
      onDecide={decision => onDecide(decision, decision === 'approve' && !unasked ? 'ask_scripts' : undefined)}
    >
      <SkillShown skill={skill} />
      <ScriptsLeave id={`skill-leave-${skill.tool_call_id}`} skill={skill} texts={skill.script_texts} checked={unasked} onChange={setUnasked} />
      <div className="muted cmd-approval-note">
        {skill.roles.length > 0 ? `Given to: ${skill.roles.join(', ')}.` : 'Given to no role yet.'} Its text is what their
        agents are told: a skill from elsewhere can steer them. A copy is kept; nothing is copied, nor downloaded beyond
        what is shown here, before you say yes.
      </div>
    </DecisionCard>
  )
}
