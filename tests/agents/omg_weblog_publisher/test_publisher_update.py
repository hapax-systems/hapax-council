from agents.omg_weblog_publisher.publisher import update_syndication_links


def test_update_syndication_links_dry_run(monkeypatch):
    """Test that the update method handles URLs without throwing if client disabled."""
    # Since we can't test actual API interactions without hitting the network,
    # we just ensure it handles disabled clients gracefully.
    monkeypatch.setenv("HAPAX_OMG_LOL_API_KEY", "")
    update_syndication_links("test-slug", ["https://mastodon.social/@test"])
    # If it doesn't raise, the early exit works.
