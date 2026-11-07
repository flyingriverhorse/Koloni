import { beforeEach, expect, test } from 'vitest'
import { applyTheme, getStoredTheme, toggleTheme } from './theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.className = ''
})

test('toggle stores the choice and sets the dark class', () => {
  applyTheme('light')
  expect(toggleTheme()).toBe('dark')
  expect(document.documentElement.classList.contains('dark')).toBe(true)
  expect(localStorage.getItem('koloni-theme')).toBe('dark')
  expect(getStoredTheme()).toBe('dark')
})
