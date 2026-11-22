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

/** Settings › After a change: what it does in this project now - live as the choice and Fix rounds change. */
export function afterChangeSaid(project: Testing & Pick<Project, 'review_lines' | 'review_files'>, after: Project['after_change'], fix: number): string {
  if (after === 'nothing') return 'Nothing is tested or reviewed; each answer says Not checked.'
  const review =
    after === 'check'
      ? `; a change over ${project.review_lines} lines or ${project.review_files} files, or one touching sign-in, secrets or commands, is read by a Reviewer (one more model request)`
      : '; no review'
  return `Runs ${testsRun(project)}, related tests first, the whole suite in the background${review}. Failing work goes back up to ${times(fix)}.`
}

/** The permission menu's switch, of what runs: "runs <command> after each change, then a Reviewer reads big or security changes. Failing work goes back to be fixed, up to N times." */
export function runsSaid(command: string, review: boolean, rounds: number): string {
  return `runs ${command} after each change${review ? ', then a Reviewer reads big or security changes' : ''}. Failing work goes back to be fixed, up to ${times(rounds)}.`
}
