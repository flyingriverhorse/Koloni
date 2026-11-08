import type { PendingRole } from '../api/types'
import { RoleCard, type SpawnDecision } from './SpawnApproval'

interface Props {
  role: PendingRole
  onDecide: (decision: SpawnDecision) => Promise<void>
}

/** Asks before an agent adds a role to your list: name, purpose, instructions and tools. */
export function RoleApproval({ role, onDecide }: Props) {
  return <RoleCard role={role} onDecide={onDecide} />
}
