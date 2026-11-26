import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { JudgeOut } from '../api/types'

/** §8: whether the Judge model asked now is one whose measurement passed (`/api/judge`'s `now.measured`), so the
 *  judge's box for your words works on it - asked only where `ask` (no old choice says so already); false until the
 *  answer comes, and where none does. */
export function useJudgeMeasured(ask: boolean): boolean {
  const [measured, setMeasured] = useState(false)
  useEffect(() => {
    if (!ask) return
    let live = true
    api.get<JudgeOut>('/judge').then(
      judge => live && setMeasured(judge?.now?.measured === true),
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [ask])
  return measured
}
