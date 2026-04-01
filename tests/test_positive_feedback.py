def test_high_engagement_accelerates():
    from agents.imagination_loop import should_accelerate_from_engagement

    assert (
        should_accelerate_from_engagement({"presence_probability": 0.9, "audio_energy": 0.5})
        is True
    )


def test_low_engagement_does_not():
    from agents.imagination_loop import should_accelerate_from_engagement

    assert (
        should_accelerate_from_engagement({"presence_probability": 0.2, "audio_energy": 0.1})
        is False
    )


def test_borderline_no_acceleration():
    from agents.imagination_loop import should_accelerate_from_engagement

    assert (
        should_accelerate_from_engagement({"presence_probability": 0.6, "audio_energy": 0.4})
        is False
    )
