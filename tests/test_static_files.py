def test_template_source_is_not_served(client):
    # templates/ used to be mounted at /static, which exposed the raw Jinja source of every page
    assert client.get("/static/base.html").status_code == 404


def test_assets_are_still_served(client):
    assert client.get("/assets/images/favicon.ico").status_code == 200
