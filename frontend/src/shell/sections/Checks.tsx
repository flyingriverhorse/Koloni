import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { part, Row } from './part'

/** When a commit of what was taken is offered, and the rest of that note, which is folded under it. */
const COMMIT_OFFERED = 'One commit per piece of work. Offered on the card once the changes are in, and only where this folder is the top folder of a git repository.'
const COMMIT_REST =
  'Always your click: never made by itself, never in a trigger’s turn. It commits only the files taken in from the sub-agent, edited ones too, with your repository’s own name and hooks. Nothing is pushed.'

/** This project › Checks and git: what is run on a sub-agent's work before it is added, and how it reaches git. */
export function useChecks(project: Project, shown: boolean) {
  const [checkCommand, setCheckCommand] = useState(project.check_command ?? '')
  const [measureCommand, setMeasureCommand] = useState(project.measure_command ?? '')
  const [gitCommit, setGitCommit] = useState(project.git_commit)
  // D2: how finished branches reach the user's - and, read when the section opens, why a pull request cannot be chosen.
  const [finishWay, setFinishWay] = useState(project.finish_way ?? null)
  const [prOff, setPrOff] = useState<string | null | undefined>(undefined)
  useEffect(() => {
    if (!shown || prOff !== undefined) return
    api.get<{ why_not: string | null }>(`/projects/${project.id}/pull-request`).then(
      read => setPrOff(read.why_not),
      err => setPrOff(errorText(err)),
    )
  }, [shown, prOff, project.id])
  const patch = {
    ...(checkCommand.trim() !== (project.check_command ?? '') && { check_command: checkCommand.trim() }),
    ...(measureCommand.trim() !== (project.measure_command ?? '') && { measure_command: measureCommand.trim() }),
    ...(gitCommit !== project.git_commit && { git_commit: gitCommit }),
    ...(finishWay && finishWay !== project.finish_way && { finish_way: finishWay }),
  }
  return part(
    patch,
    true,
    <>
      <h2>When a sub-agent’s work is added</h2>
      <Row
        label="Test before adding"
        htmlFor="check-command"
        whyId="check-command-more"
        doc={GUIDE.settingsChecks} why="What it writes to the copy’s own files is put back afterwards; the dependency folders (node_modules, .venv, venv) are linked from the project, so they are the project’s own. When work nobody watches fails it, the copy is kept for you."
        warn={
          // What it runs, on what and where, and what it does not undo, stays in sight; only how it works is behind ⓘ.
          <span id="check-command-note" className="choice-note">
            This command runs first on the sub-agent’s changes together with what the project changed meanwhile, in the
            sub-agent’s working copy, where this project’s commands run. Only exit code 0 passes. If it fails, you decide;
            work nobody watches is not added. Empty: no test. It runs by itself only where commands do: in Full auto, and in
            a trigger’s run that has this very command ticked. In “Ask before changes” and “Auto-edit files” the card
            shows the changes first and you start it there: it runs what the agent wrote. What it writes into
            node_modules, .venv or venv stays.
          </span>
        }
      >
        <input id="check-command" className="input mono" value={checkCommand} maxLength={500} placeholder="python -m pytest -q" aria-describedby="check-command-note check-command-more" onChange={e => setCheckCommand(e.target.value)} />
      </Row>
      <Row
        label="Measure command"
        htmlFor="measure-command"
        whyId="measure-command-more"
        doc={GUIDE.settingsChecks} why="The last line of its output is a number from 0 to 100: the score of a sub-agent’s work, measured in its working copy. Empty: nothing is measured."
      >
        <input id="measure-command" className="input mono" value={measureCommand} maxLength={500} placeholder="python measure.py" aria-describedby="measure-command-more" onChange={e => setMeasureCommand(e.target.value)} />
      </Row>
      <label className="choice">
        {/* Named as it was, by all of its note: a browser leaves a closed hint out of a name, and would add its button’s name to it. */}
        <input type="checkbox" aria-label={`Save each sub-agent’s work as a git commit ${COMMIT_OFFERED} ${COMMIT_REST}`} checked={gitCommit} onChange={e => setGitCommit(e.target.checked)} />
        <span>
          Save each sub-agent’s work as a git commit
          <span className="choice-note">
            {COMMIT_OFFERED} <Hint doc={GUIDE.settingsChecks}>{COMMIT_REST}</Hint>
          </span>
        </span>
      </label>
      <FinishWay finishWay={finishWay} setFinishWay={setFinishWay} prOff={prOff} />
    </>,
  )
}

/** How a team's finished branch reaches yours; a pull request greyed out with why, where it cannot be one. */
function FinishWay({ finishWay, setFinishWay, prOff }: { finishWay: Project['finish_way']; setFinishWay: (way: 'merge' | 'pull_request') => void; prOff: string | null | undefined }) {
  return (
    <fieldset className="choice" aria-label="How finished work reaches main">
      <legend>How a team’s finished branch reaches yours</legend>
      <label>
        <input type="radio" name="finish-way" checked={finishWay === 'merge'} onChange={() => setFinishWay('merge')} /> Merge here
      </label>{' '}
      <label title={prOff ?? undefined}>
        <input type="radio" name="finish-way" checked={finishWay === 'pull_request'} disabled={prOff !== null} onChange={() => setFinishWay('pull_request')} />{' '}
        Open a pull request
        {prOff && <span className="choice-note"> Not now: {prOff}.</span>}
      </label>
      <span className="choice-note">
        {finishWay === null ? 'Not chosen yet: the first finished branch on a GitHub project asks. ' : ''}A pull request lets
        KOLONİ push this project’s finished <span className="mono">koloni/</span> branches to GitHub and open one with gh; it
        never merges it. Only once your branch is on GitHub: none of your own commits go up with it. A pushed branch runs
        the repository’s own CI (<span className="mono">on: push</span>).
      </span>
    </fieldset>
  )
}
