import { expect, test } from 'vitest'
import { codeKind } from './codeKind'

test('a file path, by its slashes, its extension, a leading dot or a drive', () => {
  for (const text of ['app/views.py', 'README.md', 'C:\\Users\\x\\a.txt', 'src/', '.env', '.gitignore', '"C:\\Program Files\\a b.txt"'])
    expect(codeKind(text), text).toBe('path')
})

test('a command, by its known first word and its arguments', () => {
  for (const text of ['pytest tests/test_views.py', 'npm run build', 'git status', 'Get-ChildItem -Recurse', 'Select-String -Path a.txt x'])
    expect(codeKind(text), text).toBe('command')
})

test('anything else is neither: a name, a value, code, an address, a command word alone', () => {
  for (const text of ['test_empty_title', 'true', 'null', 'x = 1', 'https://example.com', 'npm', 'os.path', 'v1.2', 'a b.txt'])
    expect(codeKind(text), text).toBeNull()
})
