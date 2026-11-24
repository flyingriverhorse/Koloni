import { Row } from './part'

/** Where KOLONİ's saved command came from, in words. */
const WHENCE: Record<string, string> = {
  guess: 'from the project’s files',
  agent: 'an agent ran it',
  look: 'its look at the code found it',
}

/**
 * S1b: the test command(s) KOLONİ saved itself, by folder, and where each came from - the end check runs them as the
 * project's; a command of yours (a part's in This folder, the whole project's too) always wins. Forget: found again.
 */
export function FoundTests({
  found,
  forget,
  setForget,
}: {
  found: Record<string, { command?: string; from?: string; at?: string }>
  forget: boolean
  setForget: (on: boolean) => void
}) {
  const folders = Object.keys(found)
  if (!folders.length) return null
  return (
    <Row label="Found by KOLONİ">
      <span data-testid="tests-found">
        {folders.map(folder => (
          <span key={folder} className="choice-note">
            <code>{found[folder].command}</code> in <code>{folder === '.' ? './' : `${folder}/`}</code> -{' '}
            {WHENCE[found[folder].from ?? ''] ?? 'found'}
            {found[folder].at && `, ${found[folder].at.slice(0, 10)}`}.
          </span>
        ))}
        <label className="choice">
          <input type="checkbox" checked={forget} onChange={e => setForget(e.target.checked)} />
          <span>
            Forget it
            <span className="choice-note">
              KOLONİ saved it the first time it really ran tests. Yours wins: set a part’s test command in This folder -
              the whole project’s too. Forgotten, it is found again at the next change.
            </span>
          </span>
        </label>
      </span>
    </Row>
  )
}
