from app.bot.intent import classify


def test_weather_intent():
    tags = classify("will it rain this afternoon?")
    assert tags == {"weather"}


def test_train_intent():
    tags = classify("any delays on the Paoli/Thorndale line?")
    assert "trains" in tags


def test_traffic_intent():
    tags = classify("how is I-95 right now?")
    assert "traffic" in tags


def test_commute_expands_to_multi():
    tags = classify("how's my commute looking?")
    assert {"weather", "trains", "alerts"}.issubset(tags)


def test_unknown_defaults_to_lean_set():
    tags = classify("hello there")
    assert tags == {"weather", "alerts", "trains"}
