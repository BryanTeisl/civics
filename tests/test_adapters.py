from civicpulse.adapters import get_adapter, list_adapters


def test_all_expected_adapters_registered():
    names = list_adapters()
    for expected in ("primegov", "legistar", "civicclerk", "civicplus", "boarddocs", "granicus"):
        assert expected in names


def test_civicclerk_normalizes_api_url_to_human_portal():
    adapter = get_adapter("civicclerk")
    assert adapter is not None
    assert adapter.normalize_portal_url("https://fortcollinsco.api.civicclerk.com/v1") == "https://fortcollinsco.portal.civicclerk.com/"


def test_primegov_and_legistar_url_normalization():
    pg = get_adapter("primegov")
    leg = get_adapter("legistar")
    assert pg.normalize_portal_url("https://thorntonco.primegov.com/api/v2") == "https://thorntonco.primegov.com/public/portal"
    assert leg.normalize_portal_url("https://erie.legistar.com/Calendar.aspx") == "https://erie.legistar.com/"
