import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { GitStatus as Git } from '../api/types'
import { useApp } from '../state/store'
import { SECTIONS, gitLabel, gitRows, lastCommit } from './gitMap'
import { usePanel } from './usePanel'

/**
 * The project's git in the top bar (slice 70): "⑂ main · 4 changed", and under it, as it opens, Where the work is
 * (sample A, 7 Nov) - your branch, the agents' copies of this chat, the other branches - each piece of work with how it
 * stands in words. Read with git only; nothing is shown for a folder that is no repository. Read again at each turn's
 * end and as it opens.
 * Not a dialog: a region beside the page, closed with Esc or a click elsewhere.
 * K-dallar: each branch can be looked at read only, and a local one switched to - only while the server says
 * nothing holds the project there (`switch_blocked`: a turn at work, a Take in, files not committed).
 */
export function GitStatus({ projectId }: { projectId: string }) {
  const conv = useApp(s => (s.conv?.conversation.project_id === projectId ? s.conv : null))
  const asked = useApp(s => s.gitAsked)
  // K-git-not: New branch, folded behind its button - whether it is open, and its name as typed.
  const [naming, setNaming] = useState(false)
  const [made, setMade] = useState('')
  const newBranch = useRef<HTMLButtonElement>(null)
  const form = useRef<HTMLFormElement>(null)
  const stopNaming = () => {
    setNaming(false)
    newBranch.current?.focus()
  }
  // The panel takes Esc first: in the open New branch it folds that, not the map.
  const { open, setOpen, close, button, panel } = usePanel<HTMLElement>(() => {
    if (!naming || !form.current?.contains(document.activeElement)) return true
    stopNaming()
    return false
  })
  const [git, setGit] = useState<Git | null>(null)
  const [switching, setSwitching] = useState(false)
  const [refused, setRefused] = useState<string | null>(null)
  const shownFor = useRef<string | null>(null) // (the project whose git is shown: `take`)
  const read = (seen: Git | null) => {
    shownFor.current = seen ? projectId : null
    setGit(seen)
    useApp.setState({ gitBranch: seen?.branch ?? null })
  }
  // How many times it was opened: read again as it opens, not as it closes - and while it is open, a few seconds after
  // each answer: a turn's agents move on, and an answer read just before they did would stay (the 70 e2e under load).
  const [opened, setOpened] = useState(0)
  const openNow = useRef(open)
  useEffect(() => {
    openNow.current = open
  })
  const show = () => {
    setOpen(true)
    setOpened(n => n + 1)
  }
  // B-186: read again at a turn's end and as what reaches the project moves after it - a take in, an Undo, a commit.
  // shortcut: a change made outside KOLONİ shows once one of these happens or the map opens; read on focus if missed.
  // (Only what is in the project: a change proposed, or in a copy, has not reached it.)
  const reached = conv?.fileChanges.filter(c => c.status === 'applied' || c.status === 'reverted').map(c => c.id + c.status) ?? []
  const ended = conv
    ? [...conv.runs.filter(r => r.ended_at).map(r => r.id), ...conv.merges.map(m => m.status + (m.commit?.state ?? '')), ...reached].join()
    : ''
  useEffect(() => {
    let gone = false
    let again: ReturnType<typeof setTimeout> | undefined
    const take = (seen: Git | null) => {
      if (gone) return
      // An open map keeps what it shows through a read with no answer (git slower than its 5 s on a big repository, the
      // server not reached): only where nothing was read yet, or the map is closed, is there no git.
      // shortcut: a project that stops being a repository while its map is open shows its last git until it is closed.
      if (seen || !openNow.current || shownFor.current !== projectId) read(seen)
      // (the next read only once this one is in: a slow one is never cut short by it)
      if (openNow.current) again = setTimeout(() => setOpened(n => n + 1), 3000)
    }
    api.get<Git | null>(`/projects/${projectId}/git`).then(
      // (Not what this page knows - a server from before slice 70: no git.)
      seen => take(seen && Array.isArray(seen.worktrees) ? seen : null),
      () => take(null),
    )
    return () => {
      gone = true
      clearTimeout(again)
    }
  }, [projectId, ended, opened])
  // "Show git" in the chat: opened from there.
  const [took, setTook] = useState(asked)
  if (asked !== took) {
    setTook(asked)
    show()
  }
  if (!git) return null
  const label = gitLabel(git)
  const see = (agentId: string, copy: boolean) => {
    close()
    if (copy) useApp.getState().openFiles(`copy:${agentId}`)
    else useApp.getState().select(`agent:${agentId}`)
  }
  const switchTo = (name: string, isNew = false) => {
    setSwitching(true)
    setRefused(null)
    api
      .post<Git | null>(`/projects/${projectId}/git/switch`, { name, new: isNew })
      .then(
        seen => {
          // (the Workspace is made anew on the branch read here: `gitBranch`, its key)
          read(seen)
          // (a read asked for before the switch, still on its way, would put the old branch back: it is dropped, and
          // git read again)
          setOpened(n => n + 1)
          if (isNew) {
            setMade('')
            stopNaming()
          }
        },
        error => setRefused(errorText(error)),
      )
      .finally(() => setSwitching(false))
  }
  const work = gitRows(git, conv)
  return (
    <>
      <button
        ref={button}
        type="button"
        className="git-button mono"
        aria-expanded={open}
        aria-controls="git-map"
        title={`${label} - the project's git: what works where, and where it goes`}
        onClick={() => (open ? close() : show())}
      >
        {label}
      </button>
      {open && (
        <section ref={panel} id="git-map" tabIndex={-1} className="allow-list-panel git-map" aria-labelledby="git-map-title">
          <h3 id="git-map-title" className="git-title">
            Where the work is
          </h3>
          <p className="muted git-note">From git, read only. KOLONİ changes nothing here but the branch you switch to.</p>
          <h4 className="kicker">Your branch</h4>
          <div className="git-row">
            <span className="git-what">
              <b className="mono">{git.branch || 'no branch'}</b> · now
              <small>
                {git.changed > 0 ? `${git.changed} ${git.changed === 1 ? 'file' : 'files'} not saved in git yet` : 'everything is saved in git'}
                {git.current && <span className="mono"> · last commit {lastCommit(git.current)}</span>}
              </small>
            </span>
            {/* shortcut: the Workspace - the project's tree and what this chat changed - not git's own diff; add one if missed. */}
            <button
              type="button"
              className="btn btn-small"
              onClick={() => {
                close()
                useApp.getState().openFiles()
              }}
            >
              See changes
            </button>
          </div>
          {git.switch_blocked && <p className="muted git-note">Can't switch branches now: {git.switch_blocked}.</p>}
          <form
            ref={form}
            className="git-new"
            onSubmit={event => {
              event.preventDefault()
              switchTo(made.trim(), true)
            }}
            // (left empty: folded again)
            onBlur={event => {
              if (!made.trim() && !event.currentTarget.contains(event.relatedTarget)) setNaming(false)
            }}
          >
            <button
              ref={newBranch}
              type="button"
              className="btn btn-small"
              aria-expanded={naming}
              disabled={!!git.switch_blocked}
              title={git.switch_blocked ?? `a branch made where ${git.branch || 'the project'} stands, and the project onto it`}
              onClick={() => setNaming(on => !on)}
            >
              + New branch
            </button>
            {naming && (
              <>
                <input className="mono" aria-label="New branch name" placeholder="new-branch-name" value={made} maxLength={200} autoFocus onChange={event => setMade(event.target.value)} />
                <button type="submit" className="btn btn-small" disabled={switching || !!git.switch_blocked || !made.trim()} title={git.switch_blocked ?? undefined}>
                  Create
                </button>
              </>
            )}
          </form>
          {refused && (
            <p role="alert" className="git-note">
              {refused}
            </p>
          )}
          {SECTIONS.map(([section, title]) => {
            const rows = work.filter(row => row.section === section)
            if (rows.length === 0) return null
            return (
              <div key={section} role="group" aria-label={title}>
                <h4 className="kicker">{title}</h4>
                <ul className="git-branches">
                  {rows.map(row => (
                    <li key={row.key} className="git-row">
                      <span className="git-what">
                        <b>{row.what}</b> · <span className={`git-state git-state-${row.tone}`}>{row.state}</span>
                        {row.small && <small>{row.small}</small>}
                      </span>
                      {row.act && (
                        <button type="button" className={`btn btn-small${row.act.label === 'Take in…' ? ' btn-primary' : ''}`} onClick={() => see(row.act!.agentId, row.act!.copy)}>
                          {row.act.label}
                        </button>
                      )}
                      {row.branch && (
                        <button
                          type="button"
                          className="btn btn-small"
                          title={`${row.branch.name}'s files in the Workspace, read only - nothing is switched`}
                          onClick={() => {
                            close()
                            useApp.getState().lookAt(row.branch!.ref)
                          }}
                        >
                          Look
                        </button>
                      )}
                      {row.branch && !row.branch.remote && (
                        <button
                          type="button"
                          className="btn btn-small"
                          disabled={switching || !!git.switch_blocked || !!row.branch.worktree}
                          title={row.branch.worktree ? `open in its own folder ${row.branch.worktree}: git switches to it only there` : (git.switch_blocked ?? `the project goes onto ${row.branch.name}`)}
                          onClick={() => switchTo(row.branch!.name)}
                        >
                          Switch to
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </section>
      )}
    </>
  )
}
