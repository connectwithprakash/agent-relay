from app.config import Settings


def test_postgres_url_uses_installed_psycopg_driver():
    settings = Settings(
        database_url="postgresql://relay:secret@db:5432/relay",
    )

    assert settings.is_postgres is True
    assert (
        settings.sqlalchemy_database_url
        == "postgresql+psycopg://relay:secret@db:5432/relay"
    )


def test_fly_style_postgres_url_uses_installed_psycopg_driver():
    settings = Settings(
        database_url="postgres://relay:secret@db:5432/relay",
    )

    assert settings.is_postgres is True
    assert (
        settings.sqlalchemy_database_url
        == "postgresql+psycopg://relay:secret@db:5432/relay"
    )


def test_explicit_sqlalchemy_driver_is_preserved():
    url = "postgresql+psycopg://relay:secret@db:5432/relay"
    settings = Settings(database_url=url)

    assert settings.sqlalchemy_database_url == url
