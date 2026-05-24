"""Unit tests for the bot's entity extraction (route, rail line)."""
from app.bot.entities import extract_line, extract_route


# ── extract_route ──────────────────────────────────────────────────────────


def test_route_from_to():
    assert extract_route("Should I drive from Wayne to Center City?") == (
        "Wayne",
        "Center City",
    )


def test_route_strips_trailing_time_qualifier():
    assert extract_route(
        "Quickest way from 30th Street Station to Fishtown tonight?"
    ) == ("30th Street Station", "Fishtown")


def test_route_strips_at_clock_time():
    assert extract_route("from Wayne to Suburban Station at 5 pm") == (
        "Wayne",
        "Suburban Station",
    )


def test_route_to_only_uses_default_origin():
    assert extract_route("Should I drive to the airport?", default_origin="Wayne") == (
        "Wayne",
        "the airport",
    )


def test_route_to_only_ignored_without_default_origin():
    assert extract_route("Should I drive to the airport?") is None


def test_route_to_only_rejects_pronoun_destination():
    # "drive to work" without a real place name shouldn't trigger a route call.
    assert extract_route("when should I leave for work?", default_origin="Wayne") is None


def test_route_no_match():
    assert extract_route("how's the weather?", default_origin="Wayne") is None
    assert extract_route("any delays?", default_origin="Wayne") is None


# ── extract_line ───────────────────────────────────────────────────────────


def test_line_paoli_alias():
    assert extract_line("how's the paoli line right now?") == "Paoli/Thorndale"


def test_line_canonical_name():
    assert extract_line("any delays on Paoli/Thorndale?") == "Paoli/Thorndale"


def test_line_airport():
    assert extract_line("next airport line train") == "Airport"


def test_line_wilmington():
    # Bare "Wilmington" (the city) shouldn't match; "Wilmington line" should.
    assert extract_line("I'm visiting Wilmington tomorrow") is None
    assert extract_line("Wilmington line status?") == "Wilmington/Newark"


def test_line_no_match():
    assert extract_line("how's traffic on I-95?") is None
    assert extract_line("will it rain?") is None
