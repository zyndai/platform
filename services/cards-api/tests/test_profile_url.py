import config
from services.card_view import cite_as


def test_profile_url_defaults_to_the_cards_site(monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.zynd.ai")
    assert config.profile_url("ada") == "https://cards.zynd.ai/p/ada"


def test_profile_url_follows_the_configured_origin_without_a_double_slash(monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "http://localhost:3002/")
    assert config.profile_url("ada") == "http://localhost:3002/p/ada"


def test_profile_url_keeps_a_hostile_handle_inside_its_path_segment(monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.zynd.ai")
    assert config.profile_url('ada/"><x') == "https://cards.zynd.ai/p/ada%2F%22%3E%3Cx"


def test_cite_as_is_the_profile_url_or_the_site_without_a_handle(monkeypatch):
    monkeypatch.setattr(config, "SITE_BASE_URL", "https://cards.zynd.ai/")
    assert cite_as("ada") == "https://cards.zynd.ai/p/ada"
    assert cite_as("") == "https://cards.zynd.ai"
