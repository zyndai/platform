"""Parse commands from X mention text."""
import re
from enum import Enum


class Command(str, Enum):
    CREATE_PROFILE = "CREATE_PROFILE"
    UPDATE_PROFILE = "UPDATE_PROFILE"
    FIND_CONNECTIONS = "FIND_CONNECTIONS"
    HELP = "HELP"
    ONBOARDING_ANSWER = "ONBOARDING_ANSWER"  # free-text reply during onboarding


_CREATE = re.compile(
    r"\b(create|make|build|generate|setup|set up)\b.{0,30}\bprofile\b",
    re.IGNORECASE,
)
_UPDATE = re.compile(
    r"\b(update|edit|change|refresh)\b.{0,30}\bprofile\b",
    re.IGNORECASE,
)
_CONNECT = re.compile(
    r"\b(who should i (meet|connect|talk)|find (connections|people|matches))\b",
    re.IGNORECASE,
)


def strip_mention(text: str, bot_handle: str = "ZyndAI") -> str:
    """Remove @ZyndAI mention(s) and leading whitespace from tweet text."""
    cleaned = re.sub(rf"@{re.escape(bot_handle)}\b", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def parse_command(text: str, is_reply_to_bot: bool = False) -> Command:
    """
    Classify tweet text as a Command.

    is_reply_to_bot: True when this tweet is a direct reply to a bot tweet
    (i.e. the user is answering an onboarding question).
    """
    body = strip_mention(text)

    if is_reply_to_bot:
        # A reply during an active onboarding conversation is always an answer
        return Command.ONBOARDING_ANSWER

    if _CREATE.search(body):
        return Command.CREATE_PROFILE
    if _UPDATE.search(body):
        return Command.UPDATE_PROFILE
    if _CONNECT.search(body):
        return Command.FIND_CONNECTIONS

    return Command.HELP
