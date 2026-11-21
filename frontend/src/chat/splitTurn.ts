import type { ReactNode } from 'react'
import type { Message, ToolCall } from '../api/types'

/** One part of a message's group in the chat, in its place: `folds` - at its turn's end it may go into the turn's steps. */
export type Piece = { key: string; node: ReactNode; folds: boolean; calls?: ToolCall[] }
/** What the chat draws of one message, part by part. */
export type Group = { message: Message; pieces: Piece[] }

/**
 * A finished turn's groups: what before its answer folds (null under two steps), what of it stays out - in its order -,
 * and the answer on. Each step is one piece - the Lead's words, a line of calls, a row -, and `calls` all the folded ones.
 */
export function splitTurn(groups: Group[], answerId: string): { fold: Group[] | null; kept: Group[]; rest: Group[]; count: number; calls: ToolCall[] } {
  const at = groups.findIndex(group => group.message.id === answerId)
  const before = groups.slice(0, Math.max(at, 0))
  // (A message's group split in two keeps its message: kept outside, it is the group it was while the turn ran.)
  const part = (folds: boolean) =>
    before.map(group => ({ message: group.message, pieces: group.pieces.filter(piece => piece.folds === folds) })).filter(group => group.pieces.length > 0)
  const fold = part(true)
  const count = fold.reduce((n, group) => n + group.pieces.length, 0)
  if (count < 2) return { fold: null, kept: [], rest: groups, count, calls: [] }
  return { fold, kept: part(false), rest: groups.slice(at), count, calls: fold.flatMap(group => group.pieces.flatMap(piece => piece.calls ?? [])) }
}
