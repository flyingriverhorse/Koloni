"""The schemas of the tools that work beside the turn's agents (0.1.11): spawn_agent's and
run_command's `background`, and the tools of the Orchestrator while its agents work. `app.tools`
offers them (`TalkMixin._offered`); their properties come with their slices."""

# D1: spawn_agent's, offered to an API Orchestrator only (`AtWorkMixin._background_offered`).
SPAWN_BACKGROUND_PROPERTY = {
    "type": "boolean",
    "description": "Optional, true: the agent starts and you go on at once; its report comes to "
    "you as a note when it ends. Meanwhile talk to the user, open others, message or stop it "
    "(stop_agent). Until its note comes, never say what it found: say it is still at work.",
}

# D3: the Orchestrator's own Stop, for an agent it opened in this turn (`AtWorkMixin.stop_agent`).
STOP_AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "stop_agent",
        "description": "Stop one agent you opened in this turn with spawn_agent, while it still "
        "works. Its work so far is kept for the user; nothing of it reaches the project. Open it "
        "again only if the user asks.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": 'Its name, as spawn_agent\'s answer gave it ("Coder 2").',
                }
            },
            "required": ["name"],
        },
    },
}
# The tools above, by name, for `_tool_call_4`'s dispatch (`AtWorkMixin._at_work_call`).
AT_WORK_TOOLS = frozenset({"stop_agent"})

# Task 8: run_command's, for the API Orchestrator where command_output and stop_command are its
# (`AtWorkMixin._command_offered_later`).
COMMAND_BACKGROUND_PROPERTY = {
    "type": "boolean",
    "description": "Optional, true: the command starts and you go on at once. Read its output "
    "with command_output, stop it with stop_command; you are told when it ends.",
}
