import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll } from 'vitest'
import { resetStoreForTests } from './state/store'
import { useVoice } from './voice/voice'

afterEach(cleanup)
// The files of a worker share their modules (isolate: false, vite.config.ts): each starts from the stores a new page has.
beforeAll(() => {
  // (And the browser storage a new page has: an earlier file's closed chat panel hid the tabs of a later one.)
  if (typeof window !== 'undefined') localStorage.clear()
  resetStoreForTests()
  useVoice.setState(useVoice.getInitialState(), true)
})

// React Flow reads a node's zoom from DOMMatrixReadOnly as its handles are measured again (the recipe board's
// useUpdateNodeInternals, B-85); jsdom has none. Stubbed as xyflow's own testing guide does: no zoom.
// (A test in the node environment, as contrast.test.ts, has no window.)
if (typeof window !== 'undefined')
  window.DOMMatrixReadOnly ??= class {
    m22 = 1
  } as unknown as typeof DOMMatrixReadOnly
