# Recipe, role and skill formats

## Recipes

A recipe kept in a folder is a JSON file in `.koloni/recipes/`, named from the recipe in lowercase ASCII
with hyphens. KOLONİ writes it when you save from the Recipes tab; you can also read or change it by
hand. A file KOLONİ cannot read is listed with the reason.

```json
{
  "name": "Bugfix",
  "graph": {
    "version": 1,
    "steps": [
      { "id": "fix", "name": "Fix it", "who": { "role": "Coder" } },
      { "id": "test", "name": "Test it", "who": { "role": "Tester" }, "done_when": "no_findings" }
    ],
    "groups": [],
    "ends": [{ "id": "end", "then": "in" }],
    "arrows": [
      { "from": "start", "to": "fix" },
      { "from": "fix", "to": "test" },
      { "from": "test", "to": "end" }
    ],
    "loops": [{ "from": "test", "to": "fix", "rounds": 2 }]
  }
}
```

- **name**: 1 to 60 characters.
- **Ids**: letters, digits, `_` and `-`, at most 40. `start` is the user's message.
- **steps** (at most 60): `id`, `name`, `who`, and optionally `done_when` (`done` or `no_findings`),
  `if_fails` (`ask` or `stop`), `ask_me` (true or false), `group` (a group's id), `when` (`"problem"`:
  only if the step before found a problem), `pos` (`{"x", "y"}` on the board).
- **who** is one of:
    - `{"role": "Coder", "most": 2}`: a role, with at most 1 to 5 agents;
    - `{"team": "Web app"}`: a team's stages;
    - `{"lead": true}`: the Orchestrator picks;
    - `{"room": ["Coder", "Reviewer"]}`: a room of 2 to 6 roles;
    - `{"experts": "all"}` (or `"stale"`, `"learned"`): the team's experts;
    - `{"candidates": "Coder", "most": 3, "target": 80, "models": "auto"}`: 2 to 5 candidates;
      `models` is `"auto"`, `"same"`, or a list of `{"provider_id", "model_id"}`.
- **groups** (at most 20): `id`, `name`, `pos`, `wait` (`all` or `first`). Steps join a group by its id.
- **ends** (at most 10): `id`, `then` (`in`: take the work in; `report`: say what was found).
- **arrows** (at most 200): `{"from", "to"}`.
- **loops** (at most 20): `{"from", "to", "rounds"}`, going back, 1 to 5 rounds.

A recipe must start from `start`, reach an end on every path, and loop only backwards with a round limit.
Only recipes kept in KOLONİ can be a team's default or picked for a chat.

## Roles

Roles have no file format. You make and change them on the Agents page.

## Skills

A skill is a folder with a `SKILL.md`, in Claude Code's form:

```markdown
---
name: my-skill
description: What it is for, in a sentence or two.
license: MIT
allowed-tools: Bash, Read
---

Instructions for the agent.
```

- **name** (required): letters, digits, `.`, `_` and `-`, starting with a letter or digit, at most 64.
- **description**: at most 1024 characters are kept.
- **license**: used if the folder has no `LICENSE` or `COPYING` file.
- **allowed-tools**: KOLONİ maps these to its groups of tools. A role that lacks them is shown, with a way
  to give them.
- At most 200 files and 5 MiB in all; `SKILL.md` at most 256 KiB; a `.zip` at most 25 MiB. Secret files
  are not copied.

## The folder's `.koloni/`

| Path | What it is |
|---|---|
| `rules.md` | The project's rules (Memory page, at most 1500 characters). Every agent is told them. |
| `settings.json` | Where commands run and the web search order (see below). |
| `recipes/` | Recipes kept in this folder. |
| `knowledge/` | Knowledge topics: each one's guide; the pages read are kept out of git. |
| `shared/` | Files teams share while they work; kept out of git. |
| `tmp/` | The agents' scratch space; kept out of git. |

`settings.json` holds only these keys:

```json
{
  "exec_location": "docker",
  "docker_image": "python:3.12",
  "docker_network": false,
  "search_order": "builtin"
}
```

`exec_location` is `host` or `docker`; `search_order` is `builtin` or `cli`. Other keys are ignored.
Settings that came from another machine are shown to you before they are used (**Use them** / **Not
now**).
