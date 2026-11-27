/**
 * A share of 100 as a bar: a meter, named for a screen reader, its number in words beside it. `mark`: a line at that
 * share (where a plan's picks go a tier lower); `hot`: filled in the warning colour - the words beside say why.
 */
export function Bar({
  label,
  value,
  mark,
  hot,
}: {
  label: string
  value: number
  mark?: number | null
  hot?: boolean
}) {
  return (
    <span
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-valuetext={`${Math.round(value)}%`}
      className={hot ? 'usage-bar usage-bar-hot' : 'usage-bar'}
    >
      <span className="usage-bar-fill" style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }} />
      {mark != null && <span className="usage-bar-mark" style={{ left: `${mark}%` }} />}
    </span>
  )
}
