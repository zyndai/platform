from models.card import AgentProfileCard, CardView, Identity


def test_identity_without_edition_is_classic():
    assert Identity().edition is None
    assert AgentProfileCard(id="c1").identity.edition is None


def test_classic_identity_serializes_without_an_edition_key():
    # #given a card that never picked an edition
    card = AgentProfileCard.model_validate({"id": "c1", "identity": {"name": "Asha", "edition": None}})
    # #then its JSON is the same shape as before editions existed
    assert "edition" not in card.model_dump(mode="json")["identity"]
    assert "edition" not in card.model_dump()["identity"]


def test_cards_built_from_scraped_text_never_carry_an_edition():
    # #given LLM output that (e.g. via a prompt-injected bio) sets an edition
    from models.card import CardSynthesis
    from services.cards import assemble_card
    synth = CardSynthesis.model_validate({"identity": {"name": "Asha", "edition": {"id": "mumbai-26"}}})
    assert synth.identity.edition is not None
    # #when the card is assembled
    card = assemble_card(synth, github_data=None, github_handle=None, x_handle=None, resume_used=False)
    # #then only the owner can pick the edition later
    assert card.identity.edition is None
    assert card.identity.name == "Asha"


def test_known_edition_round_trips_through_card_json():
    card = AgentProfileCard.model_validate({
        "id": "c1",
        "identity": {"name": "Asha", "edition": {"id": "mumbai-26", "mood": "dusk", "here_for": "hacking"}},
    })
    dumped = card.model_dump(mode="json")["identity"]["edition"]
    assert dumped == {"id": "mumbai-26", "mood": "dusk", "here_for": "hacking"}
    assert AgentProfileCard.model_validate(card.model_dump(mode="json")).identity.edition == card.identity.edition


def test_edition_defaults_mood_and_leaves_here_for_unset():
    edition = Identity.model_validate({"edition": {"id": "mumbai-26"}}).edition
    assert edition is not None
    assert edition.mood == "night"
    assert edition.here_for is None


def test_unknown_or_malformed_edition_reads_as_classic_card():
    for stored in (
        {"id": "devcon-9"},
        {"id": "mumbai-26", "mood": "neon"},
        {"id": "mumbai-26", "here_for": "partying"},
        "mumbai-26",
        "",
        None,
        [],
    ):
        card = AgentProfileCard.model_validate({"id": "c1", "identity": {"name": "Asha", "edition": stored}})
        assert card.identity.edition is None, stored
        assert card.identity.name == "Asha"


def test_card_view_exposes_edition_for_the_public_page():
    view = CardView.model_validate({"identity": {"edition": {"id": "mumbai-26", "mood": "monsoon"}}})
    assert view.model_dump(mode="json")["identity"]["edition"]["mood"] == "monsoon"
