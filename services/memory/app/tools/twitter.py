
import asyncio

import tweepy

from app.services.token_store import get_tokens


def _get_client(user_id: str) -> tweepy.Client:
    tokens = get_tokens(user_id=user_id, provider="twitter")
    if not tokens:
        raise ValueError("Twitter not connected. Please connect your X account first.")
    return tweepy.Client(access_token=tokens.get("access_token"), wait_on_rate_limit=True)


async def post_tweet(user_id: str, text: str) -> dict:
    def _post() -> dict:
        try:
            client = _get_client(user_id)
            response = client.create_tweet(text=text)
            return {"success": True, "tweet_id": response.data["id"], "text": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_post)


async def read_timeline(user_id: str, max_results: int = 10) -> dict:
    def _read() -> dict:
        try:
            client = _get_client(user_id)
            me = client.get_me()
            tweets = client.get_users_tweets(id=me.data.id, max_results=min(max_results, 100))
            return {"success": True, "tweets": [{"id": t.id, "text": t.text} for t in (tweets.data or [])]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_read)


async def send_twitter_dm(user_id: str, recipient_username: str, text: str) -> dict:
    def _send() -> dict:
        try:
            client = _get_client(user_id)
            recipient = client.get_user(username=recipient_username)
            if not recipient.data:
                return {"success": False, "error": f"User @{recipient_username} not found"}
            response = client.create_direct_message(participant_id=recipient.data.id, text=text)
            return {"success": True, "dm_id": response.data["id"]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_send)


async def read_twitter_dms(user_id: str, max_results: int = 10) -> dict:
    def _read() -> dict:
        try:
            client = _get_client(user_id)
            events = client.get_direct_message_events(max_results=min(max_results, 100))
            return {
                "success": True,
                "messages": [
                    {"id": e.id, "text": e.text, "sender_id": e.sender_id}
                    for e in (events.data or [])
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_read)
