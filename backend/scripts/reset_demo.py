from pathlib import Path

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import entities  # noqa: F401
from scripts.seed_demo import seed


if __name__ == "__main__":
    storage = Path(get_settings().invoice_storage_dir).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    removed = 0
    for document in storage.iterdir():
        if document.is_file() and document.suffix.lower() == ".pdf":
            document.unlink()
            removed += 1
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    print(f"Demo database reset complete; removed {removed} uploaded PDF file(s).")
