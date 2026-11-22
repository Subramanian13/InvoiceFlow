import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from scripts.seed_demo import seed


@pytest.fixture()
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        seed(session)
        session.info["session_factory"] = Session
        session.info["tmp_path"] = tmp_path
        yield session
    engine.dispose()


@pytest.fixture()
def client(db):
    from app.api.routes import settings

    original_storage = settings.invoice_storage_dir
    settings.invoice_storage_dir = db.info["tmp_path"] / "uploads"
    app.state.session_factory = db.info["session_factory"]
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    settings.invoice_storage_dir = original_storage

