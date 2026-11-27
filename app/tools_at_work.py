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
