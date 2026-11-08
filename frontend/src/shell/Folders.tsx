import type { Folders } from '../api/types'
import { GUIDE } from './guide'
import { Hint } from './Hint'

export type Access = 'read' | 'write'
export interface FolderRow {
  path: string
  access: Access
}

/** A list's rows from its two lists as the server keeps them; and back. */
export const rowsOf = (write: string[], read: string[]): FolderRow[] => [
  ...write.map(path => ({ path, access: 'write' as const })),
  ...read.map(path => ({ path, access: 'read' as const })),
]
export const listsOf = (rows: FolderRow[]) => ({
  also_in: rows.filter(r => r.access === 'write').map(r => r.path),
  read_in: rows.filter(r => r.access === 'read').map(r => r.path),
})

/** A path as it is compared: any case, either slash, no slash at its end. */
const plain = (path: string) => path.toLowerCase().replaceAll('\\', '/').replace(/\/+$/, '')
export const holds = (folder: string, path: string) => plain(path) === plain(folder) || plain(path).startsWith(`${plain(folder)}/`)

export const WIDE = 'Every project under it becomes writable by agents. Read is enough to look things up.'
// (A CLI is given no folder that holds a place never opened: `_add_dirs`.)
export const HOLDS = 'KOLONİ’s tools only: it holds KOLONİ’s own folder, which stays closed'

interface Props {
  /** The places never opened as the server says them; null while they are read, or when they could not be. */
  shared: Folders | null
  /** Why they could not be read, if they could not. */
  sharedError: string | null
}

/** What a CLI is given of the folders a chat may also use: said where those folders are set. */
export const GIVEN =
  'Codex, agy and Copilot are given no folder to Read: a folder Codex or Copilot is given, its own tools may write in, and agy is given none outside the project.'

/** Settings › The app › Your data: the places no agent opens, in every project. */
export function FoldersSection({ shared, sharedError }: Props) {
  return (
    <>
      {sharedError && (
        <div role="alert" className="alert">
          The places never opened could not be read: {sharedError}
        </div>
      )}
      {shared && (
        <>
          <h3 className="kicker">Always blocked</h3>
          <details className="more">
            <summary>
              {shared.never.length} places no agent ever opens: where your secrets are kept, KOLONİ itself and the system’s folders
            </summary>
            <ul className="folder-rows folder-never" aria-label="Always blocked">
              {shared.never.map(place => (
                <li key={place.path} className="muted">
                  <span className="mono">{place.path}</span> - {place.why}
                </li>
              ))}
            </ul>
          </details>
          <span className="choice-note">
            Nor any folder that holds one of them, your home folder or a drive’s root.{' '}
            <Hint doc={GUIDE.neverOpened}>
              A folder that holds KOLONİ (the Desktop, say) can still be listed: KOLONİ stays closed in it, and only KOLONİ’s own tools work
              there - no CLI is given the folder. Secrets (.env, keys, credentials, KOLONİ’s database) are never opened anywhere outside the
              project; inside it a secret file is read only after you allow it, each time (a script that does not name it, Claude Code’s Grep,
              and Codex, agy and Copilot’s own tools can still look in one unasked). The list is KOLONİ’s own and cannot be changed here.
            </Hint>
          </span>
        </>
      )}
    </>
  )
}
