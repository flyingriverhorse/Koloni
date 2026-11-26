/** A cell's colour: green, honey, red-orange, or none of its own (`theme/cell.css`). */
export type CellTone = 'ok' | 'honey' | 'warn' | 'plain'
/** How it is filled: whole, lightly, not at all - or a thin rim, lighter than an empty cell's. */
export type CellFill = 'full' | 'soft' | 'none' | 'thin'

/**
 * The honeycomb cell (0.1.10): one mark a page fills by how something stands - each page says what its tones mean
 * (Ready's: `ready/cells.ts`). Its `label` is its title and its accessible name: its colour never says it alone.
 */
export function Cell({
  tone,
  fill,
  label,
  big = false,
}: {
  tone: CellTone
  fill: CellFill
  label: string
  big?: boolean
}) {
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`cell cell-${tone} cell-${fill}${big ? ' cell-big' : ''}`}
    />
  )
}
