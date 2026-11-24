import type { Project } from '../../api/types'

type Testing = Pick<Project, 'tests_found' | 'test_commands'>

/** Where none is known yet: KOLONİ finds one, and asks you once. */
export const FINDS_ONE = 'the test command KOLONİ finds (it asks you once)'

/** A folder by its path in the project, "" the root: "./" and "web/" are the project map's keys, "." and "web" a save's. */
const folderOf = (key: string) => key.replace(/^\.(\/|$)/, '').replace(/\/$/, '')

/**
 * The test command(s) the end check runs now, as the project stands (`proof.test_runs`, `FoundMixin._runs_found`): each
 * part's test command you set on the project map, then what KOLONİ saved for any other folder; none: it finds one. `where`: with each folder, and who found it.
 * shortcut: a part the map no longer finds is still named; drop it if a project whose parts moved reads this line wrong.
 */
export function testsRun(project: Testing, where = true): string {
  const yours = Object.entries(project.test_commands ?? {}).filter(([, line]) => line.trim())
  // (A save for a folder whose part has your command is not run: yours is. Folders in one case - Windows keeps saves so.)
  const theirs = new Set(yours.map(([key]) => folderOf(key).toLowerCase()))
  const found = Object.entries(project.tests_found ?? {}).filter(([folder]) => !theirs.has(folderOf(folder).toLowerCase()))
  const named = (line: string, key: string, by = '') => (where ? `${line} in ${folderOf(key) ? `${folderOf(key)}/` : './'}${by}` : line)
  const runs = [
    ...yours.map(([key, line]) => named(line.trim(), key)),
    ...found.map(([folder, one]) => named(String(one.command), folder, ' (found by KOLONİ)')),
  ]
  return runs.length ? runs.join(', ') : FINDS_ONE
}

const times = (n: number) => `${n} time${n === 1 ? '' : 's'}`
/** k-canli-016: how far failing work goes back - until it passes (null, the default), or up to a number of times. */
const goesBack = (rounds: number | null) => (rounds === null ? 'until it passes, while each round makes progress' : `up to ${times(rounds)}`)

/** How long a turn you watch waits for its tests, in seconds: the whole suite before it goes on after the answer
 *  (`proof_later_mixin.DETACH_SECONDS`), and all of them where the work is in its own copy (`proof_mixin.END_WAIT_SECONDS`).
 *  tests/test_proof_background_scenarios.py keeps them the server's. */
export const WAITS = { detach: 60, copy: 120 }
const minutes = (seconds: number) => (seconds === 60 ? '1 minute' : seconds % 60 ? `${seconds} seconds` : `${seconds / 60} minutes`)

/** Settings › After a change: what it does in this project now - live as the choice and Fix rounds change. */
export function afterChangeSaid(project: Testing & Pick<Project, 'review_lines' | 'review_files'>, after: Project['after_change'], fix: number | null, stronger = true): string {
  if (after === 'nothing') return 'Nothing is tested or reviewed; each answer says Not checked.'
  const review =
    after === 'check'
      ? `; a change over ${project.review_lines} lines or ${project.review_files} files, or one touching sign-in, secrets or commands, is read by a Reviewer (one more model request)`
      : '; no review'
  return `Runs ${testsRun(project)}, related tests first, the whole suite in the background${review}. A turn you watch waits for the related tests (with none, at most ${minutes(WAITS.detach)} for the whole suite; in its own working copy, at most ${minutes(WAITS.copy)} for them all). Failing work goes back ${goesBack(fix)}${stronger ? ', then to a stronger model' : ''}.`
}

/** The permission menu's switch, of what runs: "runs <command> after each change, then a Reviewer reads big or security changes. Failing work goes back to be fixed, until it passes …" (or "up to N times"). */
export function runsSaid(command: string, review: boolean, rounds: number | null): string {
  return `runs ${command} after each change${review ? ', then a Reviewer reads big or security changes' : ''}. Failing work goes back to be fixed, ${goesBack(rounds)}.`
}
