// A reporter that keeps what a failed run leaves behind - each failed test's trace and
// the backend's log - in a folder the next run does not clear (e2e/_failures, not in
// git). A run in which everything passed keeps nothing.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { KEPT_DIR, LOG_DIR } from './paths.mjs'

const KEPT_RUNS = 5

export default class KeepFailures {
  failed = []
  outputDir = null

  onBegin(config) {
    this.outputDir = config.projects[0]?.outputDir ?? null
  }

  onTestEnd(test, result) {
    if (result.status === 'passed' || result.status === 'skipped') return
    const title = test.titlePath().filter(Boolean).join(' › ')
    this.failed.push(`${result.status} after ${result.duration} ms: ${title}\n${result.error?.message ?? ''}\n`)
  }

  onEnd(result) {
    if (this.failed.length === 0 && result.status === 'passed') return
    try {
      const kept = path.join(KEPT_DIR, new Date().toISOString().replace(/[:.]/g, '-'))
      mkdirSync(kept, { recursive: true })
      writeFileSync(
        path.join(kept, 'failed.txt'),
        `The run ended ${result.status}; ${this.failed.length} test(s) did not pass.\n\n${this.failed.join('\n')}`,
      )
      if (this.outputDir && existsSync(this.outputDir)) {
        cpSync(this.outputDir, path.join(kept, 'test-results'), { recursive: true })
      }
      if (existsSync(LOG_DIR)) cpSync(LOG_DIR, path.join(kept, 'logs'), { recursive: true })
      for (const old of readdirSync(KEPT_DIR).sort().slice(0, -KEPT_RUNS)) {
        rmSync(path.join(KEPT_DIR, old), { recursive: true, force: true })
      }
      console.log(`\nWhat this failed run left behind (traces, the backend's log) is kept in ${kept}`)
    } catch (error) {
      console.log(`\nWhat this failed run left behind could not be kept: ${error}`)
    }
  }
}
