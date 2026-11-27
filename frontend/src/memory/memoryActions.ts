import type { MemorySearch } from '../api/types'
import type { NewFact } from './forms'

/** The store's actions on the open project's memory (moved out of `AppStore` to keep the store's file in its size). */
export interface MemoryActions {
  /** The user's decisions on the memory; each throws ApiError, and the memory is read again. */
  approveMemory(memoryId: string, text?: string): Promise<void>
  rejectMemory(memoryId: string): Promise<void>
  restoreMemory(memoryId: string): Promise<void>
  /** Of a source that moved: these are the same lines. */
  confirmMemory(memoryId: string): Promise<void>
  correctMemory(memoryId: string, changes: { text: string; about: string | null }): Promise<void>
  writeFact(fact: NewFact): Promise<void>
  saveRules(rules: string): Promise<void>
  /** Your own preferences (22b), one text for every project; and a suggested line into them. Each throws ApiError. */
  savePreferences(text: string): Promise<void>
  addPreference(memoryId: string): Promise<void>
  /** What an agent's `recall` would find for these words, in the open project. Throws ApiError. */
  searchMemory(query: string): Promise<MemorySearch>
}
