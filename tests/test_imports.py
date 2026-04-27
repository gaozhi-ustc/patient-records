def test_core_packages_import() -> None:
    import app
    import app.api
    import app.db
    import app.worker
    import app.worker.rpa

    assert app is not None
    assert app.api is not None
    assert app.db is not None
    assert app.worker is not None
    assert app.worker.rpa is not None
