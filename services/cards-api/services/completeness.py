"""Deterministic completeness: public information, never private memory."""
from models.card import AgentProfileCard


def completeness(card: AgentProfileCard) -> dict:
    edit = f"/p/{card.handle}/edit"
    checks = [
        ("identity", "Add your name and headline", bool(card.identity.name.strip() and card.identity.headline.strip()), 20),
        ("avatar", "Add a profile photo", bool(card.identity.avatar_url.strip()), 10),
        ("summary", "Write a short introduction", bool(card.summary.strip()), 20),
        ("skills", "Add your skills", bool(card.skills), 15),
        ("projects", "Add a project", bool(card.projects), 10),
        ("presence", "Add a social profile", bool(card.identity.links), 10),
        ("signals", "Say what you are working on or looking for", bool(card.working_on or card.connect_with), 10),
        ("memory", "Approve a fact for your card", bool(card.zynd_memory), 5),
    ]
    return {"score": sum(weight for _, _, ok, weight in checks if ok),
            "actions": [{"section": key, "title": title, "href": edit + "#" + key}
                        for key, title, ok, _ in checks if not ok][:3]}
