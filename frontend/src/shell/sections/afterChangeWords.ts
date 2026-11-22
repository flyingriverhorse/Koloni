import type { Project } from '../../api/types'

type Testing = Pick<Project, 'check_command' | 'tests_found'>

/** Where none is known yet: KOLONİ finds one, and asks you once. */
export const FINDS_ONE = 'the test command KOLONİ finds (it asks you once)'

/**
 * The test command(s) the end check runs now, as the project stands: your own check command, else what KOLONİ saved by
 * folder; none: it finds one. `where`: with each folder, and who found it.
 * shortcut: a part's own test command (the project map's) is not named here; name it if a project with parts is seen
 * reading this line wrong.
 */
export function testsRun(project: Testing, where = true): string {
  const own = project.check_command?.trim()
  if (own) return where ? `${own} in ./` : own
  const found = Object.entries(project.tests_found ?? {}).map(([folder, one]) =>
    where ? `${String(one.command)} in ${folder === '.' ? './' : `${folder}/`} (found by KOLONİ)` : String(one.command),
  )
  return found.length ? found.join(', ') : FINDS_ONE
}

const times = (n: number) => `${n} time${n === 1 ? '' : 's'}`

/** How long a turn you watch waits for its tests, in seconds: the whole suite before it goes on after the answer
 *  (`proof_later_mixin.DETACH_SECONDS`), and all of them where the work is in its own copy (`proof_mixin.END_WAIT_SECONDS`).
 *  tests/test_proof_background_scenarios.py keeps them the server's. */
export const WAITS = { detach: 60, copy: 120 }
const minutes = (seconds: number) => (seconds === 60 ? '1 minute' : seconds % 60 ? `${seconds} seconds` : `${seconds / 60} minutes`)

/** Settings › After a change: what it does in this project now - live as the choice and Fix rounds change. */
export function afterChangeSaid(project: Testing & Pick<Project, 'review_lines' | 'review_files'>, after: Project['after_change'], fix: number, stronger = true): string {
  if (after === 'nothing') return 'Nothing is tested or reviewed; each answer says Not checked.'
  const review =
    after === 'check'
      ? `; a change over ${project.review_lines} lines or ${project.review_files} files, or one touching sign-in, secrets or commands, is read by a Reviewer (one more model request)`
      : '; no review'
  return `Runs ${testsRun(project)}, related tests first, the whole suite in the background${review}. A turn you watch waits for the related tests (with none, at most ${minutes(WAITS.detach)} for the whole suite; in its own working copy, at most ${minutes(WAITS.copy)} for them all). Failing work goes back up to ${times(fix)}${stronger ? ', then to a stronger model' : ''}.`
}

/** The permission menu's switch, of what runs: "runs <command> after each change, then a Reviewer reads big or security changes. Failing work goes back to be fixed, up to N times." */
export function runsSaid(command: string, review: boolean, rounds: number): string {
  return `runs ${command} after each change${review ? ', then a Reviewer reads big or security changes' : ''}. Failing work goes back to be fixed, up to ${times(rounds)}.`
}
