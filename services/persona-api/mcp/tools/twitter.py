"""
Twitter / X MCP Tools

Registered via the ContextAware framework so the agent can:
  - post_tweet       — create a new tweet
  - read_timeline    — get recent tweets from the user's home timeline
  - send_dm          — send a direct message
  - read_dms         — read recent direct messages

All functions accept a `user_id` to look up stored OAuth tokens.
"""

import tweepy
from services.token_store import get_tokens

import asyncio


def _get_client(user_id: str) -> tweepy.Client:
    """Build a Tweepy Client from stored OAuth tokens."""
    tokens = get_tokens(user_id=user_id, provider="twitter")
    if not tokens:
        raise ValueError("Twitter not connected. Please connect your X account first.")
    return tweepy.Client(
        access_token=tokens.get("access_token"),
        wait_on_rate_limit=True,
    )


def post_tweet(user_id: str, text: str) -> dict:
    """
    Post a tweet to X / Twitter.

    Args:
        user_id (str): The platform user ID (looked up from auth)
        text (str): Tweet content (max 280 chars)

    Returns:
        dict: The created tweet data or error
    """
    try:
        client = _get_client(user_id)
        response = client.create_tweet(text=text)
        return {
            "success": True,
            "tweet_id": response.data["id"],
            "text": text,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_timeline(user_id: str, max_results: int = 10) -> dict:
    """
    Read tweets from the authenticated user's timeline.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of tweets to fetch (max 100)

    Returns:
        dict: List of recent tweets
    """
    try:
        client = _get_client(user_id)
        # Get the authenticated user's ID first
        me = client.get_me()
        tweets = client.get_users_tweets(
            id=me.data.id,
            max_results=min(max_results, 100),
        )
        return {
            "success": True,
            "tweets": [
                {"id": t.id, "text": t.text} for t in (tweets.data or [])
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_dm(user_id: str, recipient_username: str, text: str) -> dict:
    """
    Send a direct message on X / Twitter.

    Args:
        user_id (str): The platform user ID
        recipient_username (str): Twitter handle to message
        text (str): Message content

    Returns:
        dict: DM send result
    """
    try:
        client = _get_client(user_id)
        # Look up recipient by username
        recipient = client.get_user(username=recipient_username)
        if not recipient.data:
            return {"success": False, "error": f"User @{recipient_username} not found"}

        response = client.create_direct_message(
            participant_id=recipient.data.id,
            text=text,
        )
        return {"success": True, "dm_id": response.data["id"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_dms(user_id: str, max_results: int = 10) -> dict:
    """
    Read recent direct messages.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of DMs to fetch

    Returns:
        dict: List of recent DMs
    """
    try:
        client = _get_client(user_id)
        events = client.get_direct_message_events(max_results=min(max_results, 100))
        return {
            "success": True,
            "messages": [
                {
                    "id": e.id,
                    "text": e.text,
                    "sender_id": e.sender_id,
                }
                for e in (events.data or [])
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
