import { describe, expect, it } from 'vitest'
import { measure } from './complexity.mjs'

describe('complexity counter', () => {
  it('counts if/else and && on top of 1, and a nested function on its own', () => {
    const rows = measure('fixture.ts', `
      function outer(a: boolean, b: boolean) {
        if (a && b) return 1
        else return [1].map(x => (x ? 2 : 3))
      }
    `)
    expect(rows.map(r => [r.name, r.value])).toEqual([['outer', 3], ['outer>map', 2]])
  })
})
