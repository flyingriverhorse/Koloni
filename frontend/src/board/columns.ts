export const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** How long since `iso`, in the largest whole unit: "<1 min", "5 min", "3 h", "2 d". */
export function since(iso: string, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return '<1 min'
  if (minutes < 60) return `${minutes} min`
  return minutes < 24 * 60 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / (24 * 60))} d`
}
