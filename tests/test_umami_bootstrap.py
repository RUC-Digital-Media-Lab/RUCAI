from app.main import _umami_bootstrap_html


def test_umami_bootstrap_disabled_without_website_id(monkeypatch):
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    assert _umami_bootstrap_html() == ""


def test_umami_bootstrap_includes_required_attributes(monkeypatch):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "57bf2170-6847-4371-a9d5-ed941ddfa657")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://cloud.umami.is/script.js")
    monkeypatch.setenv("UMAMI_HOST_URL", "https://cloud.umami.is")
    monkeypatch.setenv("UMAMI_DOMAINS", "example.com,www.example.com")

    html = _umami_bootstrap_html()
    assert "umami-script" in html
    assert "https://cloud.umami.is/script.js" in html
    assert "57bf2170-6847-4371-a9d5-ed941ddfa657" in html
    assert "https://cloud.umami.is" in html
    assert "example.com,www.example.com" in html
