"""The "Pitch me" step before booking: an owner opt-in that hides the booking links.

When the owner turns it on (identity.pitch_to_book) and has a booking link,
public reads carry no booking URL at all; the only way a visitor gets one is
POST /v1/chat/{handle}/pitch returning a pass. Hiding the button in the page
would not be enough: the link would still be in the HTML, data.json, /view and
the chat prompt for anyone who looked.
"""
from models.card import AgentProfileCard

BOOKING_LABELS = {"calendly_url": "Calendly", "google_calendar_url": "Google Calendar"}


def booking_links(card: AgentProfileCard) -> list[dict[str, str]]:
    return [{"label": label, "url": url} for field, label in BOOKING_LABELS.items() if (url := getattr(card, field))]


def is_gated(card: AgentProfileCard) -> bool:
    return card.identity.pitch_to_book and bool(booking_links(card))


def public_booking(card: AgentProfileCard) -> AgentProfileCard:
    """The card as an unauthenticated reader may see it.

    Gated: the booking URLs are withheld. Not gated: the flag is cleared, so a
    public `pitch_to_book` always means "there is a link, pitch to get it", never
    an opt-in left on with no link to protect.
    """
    if is_gated(card):
        return card.model_copy(update=dict.fromkeys(BOOKING_LABELS))
    if card.identity.pitch_to_book:
        return card.model_copy(update={"identity": card.identity.model_copy(update={"pitch_to_book": False})})
    return card
