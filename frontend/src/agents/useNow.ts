import { useEffect, useState } from 'react'

/**
 * The time now, read again every `ms` - only while the tab is in sight: hidden, no clock ticks (nothing is drawn there),
 * and the time is read again as it is shown.
 */
export function useNow(ms: number): number {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const tick = () => setNow(Date.now())
    let timer: ReturnType<typeof setInterval> | undefined
    const follow = () => {
      clearInterval(timer)
      timer = undefined
      if (document.hidden) return
      tick()
      timer = setInterval(tick, ms)
    }
    if (!document.hidden) timer = setInterval(tick, ms)
    document.addEventListener('visibilitychange', follow)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', follow)
    }
  }, [ms])
  return now
}
