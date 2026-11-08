# Adding an MCP server safely

An MCP server runs with your rights on this machine. These steps add one while keeping its tools behind
your cards.

1. **Add it.** Tools → **Add** → **A server, ready-made** (or **from its page**, pasting its setup
   text). Check the command and its arguments. Put any token in a variable, not in the arguments: "Other
   programs on this machine can see the arguments of the command".
2. **Look inside first.** For an `npx` or `uvx` server, open its row and use **What does it do?**. It
   reads the package without running it and lists what it may reach: files, programs, the network.
   "This is where to look, not a verdict."
3. **Read its tools.** Press **Read its tools**. Keep **First look for it in osv.dev's known-malware
   records** ticked.
4. **Leave it watching for a while.** Until you trust it, every call of its tools asks you on a card, at
   every level, and the card shows the tool's own description. Use it in a chat and read what it asks.
5. **Trust it** with **Trust this server** once you are content. If the page warns that it updates
   itself, pin a version in its command; otherwise your trust covers future versions too.
6. **Choose per tool.** Under **When an agent calls it**, keep **Ask** for anything that changes things,
   choose **Runs without asking** only for tools that just read, and **Off** for what you do not need.
   (At Full auto, **Ask** runs without asking.)
7. **Give it only to the roles that need it**, under **Roles that may use it**. Every tool's description
   is sent at every model step.

KOLONİ takes trust back by itself when the command or its variables change, or a new reading finds new
or changed tools.

See [MCP servers and trust](../tools/mcp.md).
