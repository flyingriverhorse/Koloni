import type { ReactNode, Ref } from 'react'

interface Props {
  /** The folder button (slice 86a): the open chat's main folder. */
  folder: ReactNode
  /** The project's git, beside it (slice 70). */
  git?: ReactNode
  title: string
  /** Where commands run, shown beside the folder. */
  location?: 'host' | 'docker'
  /** A place after the title for the canvas's turn list: given only while the canvas is shown. */
  turns?: Ref<HTMLSpanElement>
  children?: ReactNode
}

export function TopBar({ folder, git, title, location, turns, children }: Props) {
  return (
    <header className="topbar">
      <div className="topbar-title">
        {folder}
        {/* Where commands run (tek-ev: the gear went; Settings is in the rail). tag-here: only this one gives way in a
            narrow bar, theme/base.css; docker is always said. */}
        {location && <span className={location === 'docker' ? 'tag' : 'tag tag-here'}>{location === 'docker' ? 'docker' : 'this machine'}</span>}
        {git}
        <span className="muted">/</span>
        <strong title={title}>{title}</strong>
        {turns && <span ref={turns} className="topbar-turns" />}
      </div>
      <div className="topbar-right">{children}</div>
    </header>
  )
}
