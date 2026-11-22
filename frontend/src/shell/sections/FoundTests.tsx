/** Where KOLONİ's saved command came from, in words. */
const WHENCE: Record<string, string> = { guess: 'from the project’s files', agent: 'an agent ran it', look: 'its look at the code found it' }

/**
 * S1b: the test command(s) KOLONİ saved itself, by folder, and where each came from - the end check runs them as the
 * project's; a command of yours (Test before adding, or a part's in This folder) always wins. Forget: found again.
 */
export function FoundTests({ found, forget, setForget }: { found: Record<string, { command?: string; from?: string; at?: string }>; forget: boolean; setForget: (on: boolean) => void }) {
  const folders = Object.keys(found)
  if (!folders.length) return null
  return (
    <div className="set-row" data-testid="tests-found">
      <span className="set-name">Found by KOLONİ</span>
      <span className="set-value">
        {folders.map(folder => (
          <span key={folder} className="choice-note">
            <code>{found[folder].command}</code> in <code>{folder === '.' ? './' : `${folder}/`}</code> - {WHENCE[found[folder].from ?? ''] ?? 'found'}
            {found[folder].at && `, ${found[folder].at.slice(0, 10)}`}.
          </span>
        ))}
        <label className="choice">
          <input type="checkbox" checked={forget} onChange={e => setForget(e.target.checked)} />
          <span>
            Forget it
            <span className="choice-note">KOLONİ saved it the first time it really ran tests. Yours wins: set Test before adding below, or a part’s test command in This folder. Forgotten, it is found again at the next change.</span>
          </span>
        </label>
      </span>
    </div>
  )
}
