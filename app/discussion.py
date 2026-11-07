"""A discussion: several agents talking about one topic in a shared place, in rounds.

The words and rules live here; the turns themselves are run by the agent runner.
"""

from app.tools import ToolError

MAX_TOPIC_CHARS = 4000
MAX_INVITED = 5
MAX_ROUNDS = 20
DEFAULT_ROUNDS = 3
SPEECH_STEPS = 6  # a speaker may look a few things up before it speaks
# Everything said is read again by every later speaker and kept by every member, so one
# speech has to stay short. (Twenty full rounds of six speakers still come to 180 000
# characters: what ends a talk that long sooner is the conversation's discussion budget,
# where the speakers' models report what they spend.)
MAX_POST_CHARS = 1500
CUT = " [the rest was cut]"

WHY = {
    "agreed": "nobody had anything to add.",
    "round_limit": "the round limit was reached.",
    "ended_by_user": "the user ended it.",
    "too_few": "fewer than two were left to talk.",
    "budget": "its speakers' models reported more tokens than its budget allows.",
}


def plan_discussion(args: dict) -> tuple[str, list[str], int]:
    """Check a discuss call; returns the topic, who is invited and the most rounds."""
    topic = args.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ToolError("missing required argument: topic")
    topic = topic.strip()
    if len(topic) > MAX_TOPIC_CHARS:
        raise ToolError(f"the topic has at most {MAX_TOPIC_CHARS} characters")
    invited = args.get("with")
    if (
        not isinstance(invited, list)
        or not 1 <= len(invited) <= MAX_INVITED
        or not all(isinstance(name, str) and name.strip() for name in invited)
    ):
        raise ToolError(f"name 1 to {MAX_INVITED} agents or roles to talk with, in `with`")
    names = [" ".join(name.split()) for name in invited]
    if len({name.casefold() for name in names}) != len(names):
        raise ToolError("the same name twice in `with`")
    rounds = args.get("rounds", DEFAULT_ROUNDS)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= MAX_ROUNDS:
        raise ToolError(f"a discussion has 1 to {MAX_ROUNDS} rounds")
    return topic, names, rounds


def is_pass(text: str) -> bool:
    """Whether a speaker said it has nothing to add."""
    return text.strip().strip(".!").casefold() in ("pass", "")


def fit(text: str) -> str:
    """A speech as it goes into the shared place: whole, or cut to the most allowed."""
    text = text.strip()
    return text if len(text) <= MAX_POST_CHARS else text[:MAX_POST_CHARS].rstrip() + CUT


def transcript(posts: list[tuple[int, str, str, str]]) -> str:
    """What was said, round by round. A post is (round, kind, who, content)."""
    rounds: dict[int, list[str]] = {}
    for number, kind, who, content in posts:
        line = f"{who} left the discussion: {content}" if kind == "left" else f"{who}: {content}"
        rounds.setdefault(number, []).append(line)
    return "\n\n".join(
        f"Round {number}\n" + "\n\n".join(lines) for number, lines in sorted(rounds.items())
    )


def speaking_prompt(topic: str, others: list[str], said: str, number: int, most: int) -> str:
    return (
        f"You are in a discussion with {', '.join(others)}. Everyone in it reads what the "
        f"others say. Topic:\n{topic}\n\n"
        f"Said so far:\n{said or '(nothing yet)'}\n\n"
        f"It is your turn (round {number} of at most {most}). Speak to the others in a few "
        "sentences: say what you think, and where you disagree with what was said, say why. "
        "You may read files to check a claim; you cannot change anything while you are in "
        "the discussion. If you have nothing to add, reply with exactly PASS."
    )


# How what a member keeps begins: it holds the user's words too, so it is never scanned (93-A4).
MEMORY_HEAD = 'The discussion "'


def memory(topic: str, outcome: str, said: str) -> str:
    """What a member keeps of a discussion it took part in."""
    return f'{MEMORY_HEAD}{topic}" ended: {WHY[outcome]} What was said:\n\n{said}'
