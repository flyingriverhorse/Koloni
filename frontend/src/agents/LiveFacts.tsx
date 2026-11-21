import { liveFactList } from './liveLine'
import { useNow } from './useNow'

/** After what an agent does, what is known of it - " · 12s · ↓ 1.2k tokens · Fast" -, its time read every second. */
export function LiveFacts({ since, wrote, kind }: { since: string | null; wrote: number | null; kind: string | null }) {
  return <Facts pieces={liveFactList(useNow(1000), since, wrote, kind)} />
}

/**
 * The facts, each its own piece: where the line is narrow they give way before what it does, from the last - the tier,
 * then the tokens, then the time -, each whole (`.live-facts`).
 */
export function Facts({ pieces }: { pieces: string[] }) {
  if (pieces.length === 0) return null
  return (
    <span className="live-facts">
      {pieces.map((piece, at) => (
        // (By its place: the time's words change every second.)
        <span key={at}> · {piece}</span>
      ))}
    </span>
  )
}
