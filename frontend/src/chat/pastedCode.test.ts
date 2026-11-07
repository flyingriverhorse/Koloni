import { expect, test } from 'vitest'
import { asCode } from './pastedCode'

const fenced = (language: string, code: string) => `\`\`\`${language}\n${code}\n\`\`\``

test.each([
  ['python', 'import os\n\ndef greet(name):\n    return f"hi {name}"\n'],
  ['python', '#!/usr/bin/env python3\nprint("hi")\nprint("bye")'],
  ['typescript', 'interface User {\n  name: string\n}\nexport const user: User = { name: "a" }'],
  ['javascript', "import fs from 'node:fs'\nconst text = fs.readFileSync('a.txt', 'utf8')\nconsole.log(text)"],
  ['json', '{\n  "name": "koloni",\n  "private": true\n}'],
  ['sql', 'SELECT id, name\nFROM users\nWHERE active = 1\nORDER BY name;'],
])('%s is fenced with its language', (language, code) => {
  expect(asCode(code)).toEqual({ text: fenced(language, code.trimEnd()), language })
})

test('a stack trace is code in no one language', () => {
  const trace = 'Traceback (most recent call last):\n  File "app.py", line 3, in <module>\n    main()\nValueError: bad value'
  expect(asCode(trace)).toEqual({ text: fenced('', trace), language: null })
  const node = "TypeError: Cannot read properties of undefined (reading 'x')\n    at load (/app/src/a.js:10:5)\n    at main (/app/src/b.js:3:1)"
  expect(asCode(node)?.language).toBeNull()
})

test('code without a strong sign of its language gets a bare fence', () => {
  expect(asCode('#include <stdio.h>\nint main() {\n  return 0;\n}')?.language).toBeNull()
})

test('the clipboard of Windows: its line ends are made one', () => {
  expect(asCode('def a():\r\n    pass\r\nimport os\r\n')).toEqual({ text: fenced('python', 'def a():\n    pass\nimport os'), language: 'python' })
})

test.each([
  ['prose', 'Hi team,\nI looked at the report today and it reads fine.\nLet me know if you have questions.\nThanks'],
  ['a list', 'Plan:\n- read the file\n  - the second part too\n- fix the bug\n- run the tests'],
  ['two lines', 'const a = 1\nconst b = 2'],
  ['already fenced', 'look:\n```python\nprint(1)\n```'],
  ['a time after a blank line', 'Hi all,\nThe meeting moved.\n\nat 14:30 in the small room\nSee you'],
  ['a place and a time', 'See you tomorrow\n\nat the office at 10:30\nbring the slides'],
  ['chat lines that start with keywords', 'let me know when it is done\nfrom what I saw it works\nreturn the old one if not'],
  ['indented lists of other marks', 'Steps:\n  + first\n  a) second\n  1) third\n  2) fourth'],
  ['labelled lines that end in ; or [', 'Attendees: Ali; Ayşe;\nAgenda: budget (draft) [\nOk'],
])('%s stays as it is', (_, text) => {
  expect(asCode(text)).toBeNull()
})
