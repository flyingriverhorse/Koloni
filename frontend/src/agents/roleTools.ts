/** K-uzman: an expert advises and reads only - these, never a tool that writes or runs. */
export const EXPERT_TOOLS = ['list_dir', 'read_file', 'search', 'view_image', 'message_agent', 'post_note', 'read_notes', 'recall']
/** What an expert may hold at most (app/roles.py EXPERT_MAY): a role with any other tool cannot use a knowledge in full. */
export const EXPERT_MAY = ['list_dir', 'read_file', 'search', 'view_image', 'ask_user', 'message_agent', 'discuss', 'post_note', 'read_notes', 'remember', 'recall']

/** The groups a role's tools are shown in, in this order. */
export const TOOL_GROUPS = ['Files', 'Commands', 'Web', 'Browser', 'Team', 'To-do', 'Memory'] as const

export interface RoleTool {
  name: string
  group: (typeof TOOL_GROUPS)[number]
  /** Its tile's plain name and one short line (slice 81d). */
  label: string
  line: string
  hint: string
  /** It waits for the user's yes at the conversation's permission level (app.agent): writes, edits and a new role
   * at Ask; a command (not on the allowed list) and the web below Full auto. */
  asks?: true
}

/**
 * Every tool a role can be given, in the order the server keeps them.
 * shortcut: assess_task (the Assistant product owner's own job) has no tile; a role keeps it as saved, and a tile's
 * save sends it back untouched. Give it one if other roles are to assess tasks.
 */
export const ROLE_TOOLS: RoleTool[] = [
  { name: 'list_dir', group: 'Files', label: 'List folders', line: 'see what is where', hint: 'list folders' },
  { name: 'read_file', group: 'Files', label: 'Read files', line: 'open and read', hint: 'read files' },
  { name: 'search', group: 'Files', label: 'Search', line: 'find text in files', hint: 'search file contents' },
  // 28e: an image of the project, shown to its model where the model takes images.
  { name: 'view_image', group: 'Files', label: 'Look at images', line: 'pictures in the project', hint: 'look at an image of the project, shown to it if its model takes images' },
  { name: 'write_file', group: 'Files', label: 'Write files', line: 'create or replace', hint: 'create or replace files', asks: true },
  { name: 'edit_file', group: 'Files', label: 'Edit files', line: 'change parts', hint: 'change parts of files', asks: true },
  { name: 'show', group: 'Files', label: 'Show you a file', line: 'beside the chat', hint: 'put a file before you, beside the chat (every agent may, at its own work)' },
  // K-drawio: it writes the picture beside the diagram unasked, as the user decided.
  { name: 'diagram_image', group: 'Files', label: 'Diagram pictures', line: 'PNG or SVG of a .drawio', hint: 'draw a draw.io diagram of the project as a PNG or SVG picture beside it' },
  { name: 'run_command', group: 'Commands', label: 'Run commands', line: 'tests, builds, git', hint: 'run shell commands', asks: true },
  { name: 'web_search', group: 'Web', label: 'Search the web', line: 'look things up', hint: 'search the web', asks: true },
  { name: 'http_request', group: 'Web', label: 'Web requests', line: 'call an address', hint: 'make HTTP requests to the internet', asks: true },
  // Slice 51: a headless browser of its own, on this machine's previews unasked; K-tarayici-disari: and the sites you allow.
  { name: 'browser_open', group: 'Browser', label: 'Open a page', line: 'previews, sites you allow', hint: 'open a preview on this machine, a page of the project, or a site you allow, in its own headless browser' },
  { name: 'browser_screenshot', group: 'Browser', label: 'Screenshots', line: 'see the page; you too', hint: 'take a picture of the page, shown to it and to you' },
  { name: 'browser_click', group: 'Browser', label: 'Click', line: 'buttons, links, points', hint: 'click an element by selector, by its words or at a point' },
  { name: 'browser_type', group: 'Browser', label: 'Type', line: 'into a field', hint: 'type text into a field of the page' },
  { name: 'browser_key', group: 'Browser', label: 'Press keys', line: 'Enter, Tab, arrows', hint: 'press a key on the page' },
  { name: 'browser_scroll', group: 'Browser', label: 'Scroll', line: 'up and down', hint: 'scroll the page' },
  { name: 'browser_read', group: 'Browser', label: 'Read the page', line: 'text and outline', hint: "read the page's text and an outline of what can be acted on" },
  { name: 'browser_console', group: 'Browser', label: 'Console', line: 'messages and errors', hint: "read the page's console messages and errors" },
  { name: 'notify', group: 'Team', label: 'Notify you', line: 'where you set an address', hint: 'send you a notification, where you set an address' },
  { name: 'spawn_agent', group: 'Team', label: 'Open sub-agents', line: 'hand work on', hint: 'hand work to sub-agents' },
  { name: 'create_role', group: 'Team', label: 'New roles', line: 'define one', hint: 'define new roles', asks: true },
  { name: 'add_skill', group: 'Team', label: 'New skills', line: 'propose on a card', hint: 'propose a skill for you to add, on a card' },
  { name: 'ask_user', group: 'Team', label: 'Ask you', line: 'a question, on a card', hint: 'ask you questions' },
  { name: 'ask_folder', group: 'Files', label: 'Ask for a folder', line: 'outside the project, on a card', hint: 'ask you, on a card, for a folder outside the project to read or write in' },
  { name: 'message_agent', group: 'Team', label: 'Message agents', line: 'talk to the others', hint: 'talk to other agents' },
  { name: 'open_room', group: 'Team', label: 'Open rooms', line: 'several on one goal', hint: 'open a room in which several agents work on one goal together' },
  { name: 'discuss', group: 'Team', label: 'Discussions', line: 'between agents', hint: 'open a discussion between agents' },
  { name: 'read_backlog', group: 'To-do', label: 'Read the To-do list', line: 'see the project’s tasks', hint: "read the project's To-do list" },
  { name: 'add_task', group: 'To-do', label: 'Add tasks', line: 'propose one, on a card', hint: 'propose a task for the To-do list, on a card', asks: true },
  { name: 'change_task', group: 'To-do', label: 'Change tasks', line: 'propose a change, on a card', hint: 'propose a change to a task of the To-do list, on a card', asks: true },
  { name: 'propose_trigger', group: 'Team', label: 'Propose triggers', line: 'on a card', hint: 'propose a trigger for you to approve, on a card: it reads only until you give it more' },
  { name: 'post_note', group: 'Team', label: 'Leave notes', line: 'on the notebook', hint: 'leave notes on the shared notebook' },
  { name: 'read_notes', group: 'Team', label: 'Read notes', line: 'the shared notebook', hint: 'read the shared notebook' },
  { name: 'remember', group: 'Memory', label: 'Remember', line: 'note what it found', hint: "note what it found in the project's memory" },
  { name: 'recall', group: 'Memory', label: 'Recall', line: 'look in memory', hint: "look in the project's memory and in what was said in earlier messages" },
]

/** New role's "It may" (0.1.0-ui): each pack ticks its tools' tiles, and is ticked while all of them are. */
export const PACKS: [string, string, string[]][] = [
  ['Read and search', 'files, folders, images', ['list_dir', 'read_file', 'search', 'view_image']],
  ['Write code', 'write and edit files', ['write_file', 'edit_file']],
  ['Run commands', 'tests, builds, git', ['run_command']],
  ['Use the web', 'search, requests', ['web_search', 'http_request']],
]
