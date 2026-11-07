import { useState } from 'react'
import { DecisionCard, type SpawnDecision } from '../agents/SpawnApproval'
import { errorText } from '../api/client'
import type { Merge, MergeFile } from '../api/types'
import { CommitStep } from './CommitStep'
import { isKept } from './copies'
import { DiffView } from './DiffView'
import { type BranchSaid, useApp } from '../state/store'
import { worthALook } from './worthALook'

// B-189: `copies.IGNORED`, the note of a new file git ignores.
const IGNORED_BY_GIT = 'not offered: ignored by git - it is not kept'

const KIND: Record<MergeFile['kind'], string> = { new: 'new', changed: 'edit', deleted: 'deleted' }
const files = (count: number) => `${count} file${count === 1 ? '' : 's'}`
/** A few of the paths, and how many more. */
const few = (paths: string[]) => paths.slice(0, 3).join(', ') + (paths.length > 3 ? ` +${paths.length - 3} more` : '')

/** Whose side is taken of each file whose two sides clash, by its path. */
export type Choices = Record<string, 'agent' | 'project'>
/** What the card shows of each file it asks about, by path: Apply takes nothing where one moved since. */
export type Shown = Record<string, NonNullable<MergeFile['shown']>>

type Side = Choices[string]
/** The choices made on the card, by `picked`: each of a file as it was when it was made. */
type Picks = Record<string, Side>

// A choice is of the file as it was when made: shown again since (it moved), it is asked again - but for keeping the
// project's whole file, which writes nothing whatever the project holds now, and so holds for the file as it is.
const picked = (file: MergeFile, side?: Side) =>
  JSON.stringify(side === 'project' && file.whole !== false ? [file.path] : [file.path, file.shown])
const pickOf = (picks: Picks, file: MergeFile): Side | undefined =>
  picks[picked(file)] ?? (file.whole !== false ? picks[picked(file, 'project')] : undefined)
/** One choice of a file in place of any made of it before, of whatever it was then. */
function pick(picks: Picks, file: MergeFile, side: Side): Picks {
  const kept = Object.entries(picks).filter(([key]) => JSON.parse(key)[0] !== file.path)
  return { ...Object.fromEntries(kept), [picked(file, side)]: side }
}

function FileRow({ file }: { file: MergeFile }) {
  return (
    <>
      {/* Asked about again: why it is not in the project yet. */}
      {file.note && (
        <div className="muted cmd-approval-note">
          <span className="mono">{file.path}</span> — {file.note}
        </div>
      )}
    <details className="merge-file">
      <summary>
        <span className="mono merge-file-path">{file.path}</span>
        <span className="tag">{KIND[file.kind]}</span>
        {file.additions != null && file.deletions != null && (
          <span className="mono">
            <span style={{ color: 'var(--ok)' }}>+{file.additions}</span>{' '}
            <span style={{ color: 'var(--del)' }}>−{file.deletions}</span>
          </span>
        )}
      </summary>
      {file.diff != null ? (
        <div className="merge-file-diff">
          <DiffView diff={file.diff} />
        </div>
      ) : (
        <p className="muted cmd-approval-note">Not text, or too large to show: there is no diff.</p>
      )}
    </details>
    </>
  )
}

const at = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })

/** When one side last changed a file, and whether that was the later of the two. Not known: said so. */
function Side({ label, changedAt, newer }: { label: string; changedAt: string | null | undefined; newer: boolean }) {
  return (
    <span>
      {label}: {changedAt ? <time dateTime={changedAt}>{at(changedAt)}</time> : 'not known'}
      {newer && (
        <>
          {' '}
          <span className="tag tag-warn">newer</span>
        </>
      )}
    </span>
  )
}

/**
 * A file both sides changed that did not go together by itself: what stands against what, when each
 * side last changed it, and the choice - which is yours, file by file. Nothing is chosen for you:
 * "newer" is only said.
 */
function Clash({ file, name, choice, onChoose }: { file: MergeFile; name: string; choice: Choices[string] | undefined; onChoose: (side: Choices[string]) => void }) {
  const whole = file.whole !== false
  const what = whole ? 'file' : 'lines'
  const sides = file.sides
  return (
    <div className="merge-clash" role="group" aria-label={file.path}>
      {whole ? (
        <FileRow file={file} />
      ) : (
        <>
          <div className="cmd-approval-where">
            <span className="mono merge-file-path">{file.path}</span>
            <span className="tag">{KIND[file.kind]}</span>
          </div>
          <div className="muted cmd-approval-note">
            The same lines changed on both sides: <span style={{ color: 'var(--del)' }}>−</span> the project's lines,{' '}
            <span style={{ color: 'var(--ok)' }}>+</span> {name}'s.
          </div>
          <div className="merge-file-diff">
            <DiffView diff={file.clash ?? ''} />
          </div>
        </>
      )}
      {sides && (
        <div className="muted cmd-approval-where">
          <Side label="The project's file" changedAt={sides.project.changed_at} newer={sides.newer === 'project'} />
          <Side label={`${name}'s change`} changedAt={sides.agent.changed_at} newer={sides.newer === 'agent'} />
        </div>
      )}
      <div className="merge-choice" role="radiogroup" aria-label={`Whose ${what} of ${file.path}`}>
        <label className="choice">
          <input type="radio" name={`side:${file.path}`} checked={choice === 'agent'} onChange={() => onChoose('agent')} />
          <span>
            Take {name}'s {what}
          </span>
        </label>
        <label className="choice">
          <input type="radio" name={`side:${file.path}`} checked={choice === 'project'} onChange={() => onChoose('project')} />
          <span>Keep the project's {what}</span>
        </label>
      </div>
      {!whole && (file.additions ?? 0) + (file.deletions ?? 0) > 0 && file.diff != null && (
        <details className="merge-file">
          <summary>
            The rest of {name}'s changes to it is taken either way, and what else the project changed in it stays{' '}
            <span className="mono">
              <span style={{ color: 'var(--ok)' }}>+{file.additions}</span> <span style={{ color: 'var(--del)' }}>−{file.deletions}</span>
            </span>
          </summary>
          <div className="merge-file-diff">
            <DiffView diff={file.diff} />
          </div>
        </details>
      )}
    </div>
  )
}

const CHECK_STATE: Record<NonNullable<Merge['check']>['state'], [text: string, tag: string]> = {
  not_run: ['not run', 'tag'],
  running: ['running…', 'tag tag-warn'],
  // Only a check that ended with exit code 0 passed.
  passed: ['passed', 'tag tag-ok'],
  failed: ['failed', 'tag tag-del'],
}

/**
 * The project's check command, run in the agent's copy on what the card would take: how it went,
 * as far as that is known - and where commands are asked about, the button that starts it.
 */
function Check({ merge, onRun, onBranch = false }: { merge: Merge; onRun?: { off: boolean; run: () => Promise<void> }; onBranch?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const check = merge.check
  if (!check) return <div className="muted cmd-approval-note">No test command is set: not tested.</div>
  const [text, tag] = CHECK_STATE[check.state]
  const ran = check.state === 'passed' || check.state === 'failed'

  async function run() {
    if (!onRun) return
    setBusy(true)
    setError(null)
    try {
      await onRun.run()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="merge-files" role="group" aria-label="Test">
      <div className="kicker">Test</div>
      <pre className="cmd-approval-command mono">{check.command}</pre>
      <div className="cmd-approval-where">
        {/* (B-355: one not run, and why, is a warning - a red suite went in unrun) */}
        <span className={check.state === 'not_run' && check.note ? 'tag tag-warn' : tag}>{text}</span>
        {ran && check.exit_code != null && <span className="mono muted">exit code {check.exit_code}</span>}
        {check.note && <span className={check.state === 'not_run' ? undefined : 'muted'}>{check.note}</span>}
      </div>
      {ran && check.stale && (
        <div className="muted cmd-approval-note">
          This result is of an earlier state: the files have changed since the test ran.
        </div>
      )}
      {check.output && (
        <details className="merge-file">
          <summary>The end of what it wrote</summary>
          <pre className="cmd-approval-command mono">{check.output}</pre>
        </details>
      )}
      {check.state === 'running' && (
        <div className="muted cmd-approval-note">Take in and Discard wait until the test is over.</div>
      )}
      {onRun ? (
        <div className="change-actions">
          <button type="button" className="btn btn-small" disabled={busy || onRun.off || check.state === 'running'} onClick={run}>
            {ran ? 'Run the test again' : 'Run the test'}
          </button>
          <span className="muted cmd-approval-note">
            {onBranch
              ? "It runs in the branch's worktree, on what is committed there; what it writes is not merged. "
              : "It runs in the copy, on what Take in would take. What it writes to the copy's own files is put back afterwards; "}
            the dependency folders linked into {onBranch ? 'the worktree' : 'the copy'} (node_modules, .venv, venv) are
            the project's own, and what it writes there stays.
          </span>
        </div>
      ) : (
        isKept(merge) && (
          <div className="muted cmd-approval-note">
            The test is not run on a kept copy: its dependency folders are no longer linked.
          </div>
        )
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/** Where a kept copy is and that Discard deletes it, or what the working copy holds: in sight, as a branch's is (said apart). */
function copyNote(merge: Merge, name: string, kept: boolean, branch: boolean) {
  if (branch) return null
  return (
    <div className="muted cmd-approval-note">
      {kept ? (
        <>
          Its working copy is kept in <span className="mono">{merge.kept_in}</span>. Discard deletes that folder.
        </>
      ) : (
        `${name} made these in a working copy of its own. Until you decide it holds these files: another agent that wants one waits.`
      )}
    </div>
  )
}

interface Props {
  merge: Merge
  /** The agent whose changes these are. */
  name: string
  /** It did not finish its work: what it had changed so far is what is asked about. */
  unfinished?: boolean
  /** A recipe's kept copy: how its teams that ended early ended, and what Take in takes in with it (G1.3, B-84). */
  also?: string
  /** Take in (with whose side is taken of each file that clashes, and what the card shows) or Discard. */
  /** `said`: of a branch's card, keep the branch, and which way it goes (K-dal-takim D2) - only where there is one. */
  onDecide: (decision: SpawnDecision, choices?: Choices, shown?: Shown, said?: BranchSaid) => Promise<void>
  /** Run the project's check command on what the card would take. */
  onCheck?: (choices: Choices) => Promise<void>
  /** Commit the files that were taken, with this message. */
  onCommit?: (message: string, hooks?: 'with' | 'without') => Promise<void>
  /** K-devam-butce: the agent stopped at a step limit in a turn still open - Continue gives it this many more steps. */
  onContinue?: { steps: number; run: () => Promise<void> }
}

/**
 * One card for everything an agent changed in its working copy: the files, each with its
 * diff against the project as it is now; apart from them the ones the project changed too -
 * those that went together by themselves, and those of which you say whose side is taken.
 * Take in takes what the card shows; Discard throws the copy away. Once it is in the project,
 * the card goes on with the commit of those files, where that is offered.
 */
export function MergeCard({ merge, name, unfinished = false, also = '', onDecide, onCheck, onCommit, onContinue }: Props) {
  const [choices, setChoices] = useState<Picks>({})
  // K-dal-takim D2: "Keep this branch after merging", and - where the card asks - which way finished work goes.
  const [keep, setKeep] = useState(false)
  const [way, setWay] = useState<'merge' | 'pull_request'>('merge')
  // K-dallar: the branch its copy was made on, where the project is now on another (switched outside KOLONİ, or
  // by an agent): what it takes in goes onto that other branch.
  const madeOn = useApp(s => s.conv?.agents.find(a => a.id === merge.agent_id)?.copy?.branch ?? null)
  const now = useApp(s => s.gitBranch)
  const kept = isKept(merge)
  if (merge.status !== 'pending' && !kept) {
    return merge.commit ? <CommitStep merge={merge} name={name} onCommit={onCommit ?? (async () => {})} /> : null
  }
  const ready = merge.files.filter(f => f.state === 'ready')
  const merged = merge.files.filter(f => f.state === 'merged')
  const clashes = merge.files.filter(f => f.state === 'conflict' && !f.two_way)
  // Of a kept copy that does not say what it started from: nothing is known but that they differ.
  const differing = merge.files.filter(f => f.state === 'conflict' && f.two_way)
  const applied = merge.files.filter(f => f.state === 'applied')
  const refused = merge.files.filter(f => f.state === 'refused')
  // Of such a copy too: files that differ and that nothing says the agent changed - your own later work, as likely.
  // B-189: a new file git ignores in the project (generated output) is not offered either, and says so in its note.
  const ignored = merge.files.filter(f => f.state === 'left_out' && f.note === IGNORED_BY_GIT)
  const leftOut = merge.files.filter(f => f.state === 'left_out').length - ignored.length
  const open = ready.length + merged.length + clashes.length + differing.length
  // What you chose of a file that is no longer asked about, or not as it was then, says nothing.
  const said: Choices = {}
  for (const file of clashes) {
    const side = pickOf(choices, file)
    if (side) said[file.path] = side
  }
  const shown = Object.fromEntries([...ready, ...merged, ...clashes, ...differing].flatMap(f => (f.shown ? [[f.path, f.shown]] : [])))
  const unsaid = clashes.length - Object.keys(said).length
  const look = worthALook(merge.files)
  // K-dal-takim: a line's work on a git branch of its own, merged whole - not while anything clashes or is in the way.
  const branch = kept ? null : (merge.branch ?? null)
  const inTheWay = branch ? branch.conflicts.length + branch.dirty.length + (branch.note ? 1 : 0) : 0
  const pr = !!branch && (branch.way === 'pull_request' || (!!branch.ask_way && way === 'pull_request'))
  // The copy was kept on disk: no agent is at work and no file is held. Why it was kept is not
  // on record - its turn broke off, or it holds files that were not taken - so the heading says
  // only what the files say: whether some of it is in the project.
  const before =
    applied.length > 0
      ? `Some of ${name}'s changes are in the project, the rest is kept in its copy`
      : `${name}'s changes did not reach the project`
  const kicker = branch
    ? `${pr ? 'Open a pull request for' : 'Merge'} ${branch.name} into ${branch.into ?? "the project's branch"}? · ${files(open)}`
    : !kept
    ? `Take in ${name}'s work? · ${files(open)}`
    : open > 0
      ? `${before} — take in what ${differing.length > 0 ? 'its copy holds' : 'it had changed'}? · ${files(open)}`
      : `${before} — nothing ${applied.length > 0 ? 'more ' : ''}of it can be taken in from here`
  return (
    <DecisionCard
      kicker={kicker}
      // (A branch's Merge and Open pull request are their own acts: what reaches git, not a copy taken in.)
      approve={kept && open === 0 ? undefined : branch ? (pr ? 'Open pull request' : 'Merge') : 'Take in'}
      approveOff={unsaid > 0}
      off={merge.check?.state === 'running'}
      reject="Discard"
      onDecide={decision =>
        decision !== 'approve'
          ? onDecide(decision)
          : branch && (keep || branch.ask_way)
            ? onDecide(decision, said, shown, { keep_branch: keep, ...(branch.ask_way && { way }) })
            : onDecide(decision, said, shown)
      }
      also={
        kept && onContinue
          ? { label: `Continue (+${onContinue.steps} steps)`, run: onContinue.run }
          : branch?.resolve
            ? { label: 'Let an agent resolve the conflicts', run: () => useApp.getState().resolveMerge(merge.id) }
            : undefined
      }
    >
      {unfinished && (
        <div className="muted cmd-approval-note">{name} did not finish its work: this is what it had changed.</div>
      )}
      {madeOn && now && madeOn !== now && (
        <div className="muted cmd-approval-note" role="note">
          made on <span className="mono">{madeOn}</span>, the project is now on <span className="mono">{now}</span>
        </div>
      )}
      {also && <div className="muted cmd-approval-note">{also}</div>}
      {branch && inTheWay > 0 && (
        <div className="muted cmd-approval-note" role="note" aria-label="Not merged yet">
          {branch.conflicts.length > 0 && (
            <div>
              Changed on both sides, and git does not put them together:{' '}
              <span className="mono">{branch.conflicts.join(', ')}</span>
            </div>
          )}
          {branch.dirty.length > 0 && (
            <div>
              Your uncommitted changes are in the way (commit, stash or unstage them first):{' '}
              <span className="mono">{branch.dirty.join(', ')}</span>
            </div>
          )}
          {branch.note && <div>{branch.note}</div>}
          {!pr && branch.conflicts.length + branch.dirty.length > 0 && (
            <div>Merge looks again first: nothing is merged while any of this stands.</div>
          )}
          {branch.resolve && (
            <div>
              Let an agent resolve the conflicts: KOLONİ merges {branch.into ?? 'your branch'} into {branch.name} in the branch's own folder -
              your branch is not touched - and {name} puts the files together there; you see the result here first.
            </div>
          )}
        </div>
      )}
      {look.length > 0 && (
        <div className="muted cmd-approval-note" role="note" aria-label="Worth a look">
          <span className="tag tag-warn">Worth a look</span>{' '}
          {look.map(({ why, paths }, i) => (
            <span key={why}>
              {i > 0 && ' · '}
              {why}: <span className="mono">{few(paths)}</span>
            </span>
          ))}
        </div>
      )}
      {ready.length > 0 && (
        <div className="merge-files" role="group" aria-label="Files to take in">
          {ready.map(file => (
            <FileRow key={file.path} file={file} />
          ))}
        </div>
      )}
      {merged.length > 0 && (
        <div className="merge-files" role="group" aria-label="Merged with the project's changes">
          <div className="kicker">Merged with the project's changes</div>
          {merged.map(file => (
            <FileRow key={file.path} file={file} />
          ))}
          <div className="muted cmd-approval-note">
            The project changed these too. {name}'s changes and the project's are put together line by line: each diff
            shows what that does to the project's file as it is now.
            {merged.some(f => f.chose) &&
              ` Where the same lines had changed on both sides, they are as you chose: ${merged
                .filter(f => f.chose)
                .map(f => `${f.path} — ${f.chose === 'agent' ? `${name}'s` : "the project's"}`)
                .join(', ')}.`}
          </div>
        </div>
      )}
      {clashes.length > 0 && (
        <div className="merge-files" role="group" aria-label="Changed on both sides">
          <div className="kicker">Changed on both sides</div>
          {clashes.map(file => (
            <Clash key={file.path} file={file} name={name} choice={pickOf(choices, file)} onChoose={side => setChoices(c => pick(c, file, side))} />
          ))}
          <div className="muted cmd-approval-note">
            {unsaid > 0
              ? `Say whose side is taken of ${unsaid === 1 ? 'this file' : `each of these, ${unsaid} still`}: until then nothing is taken in${merge.check && !kept ? ', and the test does not run' : ''}.`
              : 'Take in takes what you chose.'}{' '}
            Nothing is chosen for you; which side is newer is only said.
          </div>
        </div>
      )}
      {differing.length > 0 && (
        <div className="merge-files" role="group" aria-label="Differs from the project">
          <div className="kicker">Differs from the project</div>
          {differing.map(file => (
            <FileRow key={file.path} file={file} />
          ))}
          <div className="muted cmd-approval-note">
            What {name}'s copy started from is not known, so these are shown against the project as it is now: each
            differs, and whether the copy or the project changed it cannot be told. Take in puts the copy's file in the
            project, over the project's where it has one; it deletes nothing. Discard keeps the project's.
          </div>
        </div>
      )}
      {leftOut > 0 && (
        <div className="muted cmd-approval-note">
          {leftOut === 1
            ? '1 other file differs from the project and is'
            : `${leftOut} other files differ from the project and are`}{' '}
          not offered: what this copy started from is not known.
        </div>
      )}
      {ignored.length > 0 && (
        <div className="muted cmd-approval-note">
          Not offered, ignored by git (not kept): <span className="mono">{ignored.map(f => f.path).join(', ')}</span>
        </div>
      )}
      {applied.length > 0 && (
        <div className="muted cmd-approval-note">
          Already in the project: <span className="mono">{applied.map(f => f.path).join(', ')}</span>
        </div>
      )}
      {refused.map(file => (
        <div key={file.path} className="muted cmd-approval-note">
          Not taken: <span className="mono">{file.path}</span>
          {file.note && ` — ${file.note}`}
        </div>
      ))}
      {open > 0 && (
        <Check merge={merge} onBranch={!!branch} onRun={!kept && onCheck ? { off: unsaid > 0, run: () => onCheck(said) } : undefined} />
      )}
      {branch?.ask_way && (
        <fieldset className="merge-way" aria-label="How finished work reaches your branch">
          <legend className="kicker">How finished work reaches {branch.into ?? 'your branch'}</legend>
          <label>
            <input type="radio" name={`way-${merge.id}`} checked={way === 'merge'} onChange={() => setWay('merge')} /> Merge here
          </label>{' '}
          <label title={branch.pr_off ?? undefined}>
            <input type="radio" name={`way-${merge.id}`} checked={way === 'pull_request'} disabled={!!branch.pr_off} onChange={() => setWay('pull_request')} /> Open a
            pull request on GitHub
            {branch.pr_off && <span className="muted"> — not now: {branch.pr_off}</span>}
          </label>
          <div className="muted cmd-approval-note">
            Kept for this project; Settings › This project › Checks and git can change it. A pull request lets KOLONİ push this project's finished
            branches to GitHub - it never merges one.
          </div>
        </fieldset>
      )}
      {branch && (
        <label className="muted cmd-approval-note">
          <input type="checkbox" checked={keep} onChange={event => setKeep(event.target.checked)} /> Keep this branch after{' '}
          {pr ? 'the pull request' : 'merging'}
        </label>
      )}
      {branch && (
        <div className="muted cmd-approval-note">
          {name} made these on branch <span className="mono">{branch.name}</span>, in a worktree of its own, where KOLONİ
          committed them.{' '}
          {pr ? (
            <>
              Open pull request pushes what the branch holds now to GitHub as one commit by KOLONİ - not the agents' own
              steps - and opens a pull request into <span className="mono">{branch.into ?? 'your branch'}</span>; nothing is
              merged here, and KOLONİ never merges it. Discard deletes the branch.
            </>
          ) : (
            <>
              Merge brings what the branch holds now into <span className="mono">{branch.into ?? 'your branch'}</span> as one
              commit by KOLONİ - not the agents' own steps - then deletes the branch, unless you keep it; Discard deletes it.
            </>
          )}
        </div>
      )}
      {copyNote(merge, name, kept, !!branch)}
    </DecisionCard>
  )
}
