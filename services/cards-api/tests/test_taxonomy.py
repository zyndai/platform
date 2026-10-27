"""The persona taxonomy behind the create page's chips."""
from models.card import CardSynthesis, WorkItem
from synthesis import taxonomy

GROUPS = {"working_on", "can_help_with", "connect_with", "love_talking_about"}


def test_every_persona_has_all_four_groups_of_distinct_labels():
    assert set(taxonomy.VOCAB) == set(taxonomy.PERSONAS)
    for persona, groups in taxonomy.VOCAB.items():
        assert set(groups) == GROUPS, persona
        for group, labels in groups.items():
            assert labels and all(labels), (persona, group)
            assert len({label.lower() for label in labels}) == len(labels), (persona, group)


def test_unknown_personas_are_dropped_not_guessed():
    assert taxonomy.normalize_persona("Product Design") == "product_design"
    assert taxonomy.normalize_persona("marketing-sales") == "marketing_sales"
    assert taxonomy.normalize_persona("wizard") == ""
    assert taxonomy.normalize_persona(None) == ""
    assert CardSynthesis.model_validate({"persona": "Creator"}).persona == "creator"
    assert CardSynthesis.model_validate({"persona": None}).persona == ""


def test_prompt_lists_every_persona_and_its_labels():
    prompt = taxonomy.prompt_section()
    for persona in taxonomy.PERSONAS:
        assert f"{persona}:" in prompt
    assert "Brand strategy" in prompt and "Code review" in prompt


def test_work_items_only_keep_http_links():
    item = WorkItem.model_validate({"title": "x", "url": "javascript:alert(1)", "image_url": "https://cdn.example/a.png"})
    assert item.url == "" and item.image_url == "https://cdn.example/a.png"
