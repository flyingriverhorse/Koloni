import { liveFacts } from './liveLine'
import { useNow } from './useNow'

/** After what an agent does, what is known of it - " · 12s · ↓ 1.2k tokens · Fast" -, its time read every second. */
export function LiveFacts({ since, wrote, kind }: { since: string | null; wrote: number | null; kind: string | null }) {
  const facts = liveFacts(useNow(1000), since, wrote, kind)
  return facts ? <span className="live-facts"> · {facts}</span> : null
}
