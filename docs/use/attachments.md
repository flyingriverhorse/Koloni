# Attachments

Attach files to a message with the attach button: **Files from this computer…**, **A screenshot from the
clipboard** (Ctrl+V), or **A file of the project…**. You can also drop files on the message box.

## Limits

- At most 10 files per message, 25 MB each.
- A video is sent as at most 8 frames.

## What the agents get

KOLONİ looks at each file's content, not only its name:

| Kind | What is sent |
|---|---|
| Text and code | The text. |
| PDF | Its text ("N pages, text taken out"), up to 500 pages. A locked PDF gives no text. |
| Word | Its text. |
| Image | The picture, to providers that take images: OpenAI-compatible servers, the Anthropic API, Claude Code and Codex. Others say it is not shown. |
| Program or script | Only its name and size. |
| A secret file (keys, passwords) | Nothing of what it holds. |

Links in a message are never fetched by KOLONİ.

**Save these to the project too** saves the attachments into the project's `docs/attachments/`, without
asking; undo takes them back.

Agents read attachments with the **Read attached files** tool, which can be switched off on the Tools page.
