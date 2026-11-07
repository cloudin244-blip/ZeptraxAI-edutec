"""
Load the website catalog (Masters programs and free courses) into MongoDB.

    python scripts/seed_catalog.py                  # loads scripts/catalog/initial_catalog.json if the catalog is empty
    python scripts/seed_catalog.py <file> --force   # replaces the whole catalog (discards edits made in the portal)

After this, the super admin manages the catalog in the University Portal (Website catalog page).
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "scripts" / "catalog" / "initial_catalog.json"


def seed(db, data, force=False):
    existing = db["CatalogProgram"].count_documents({}) + db["CatalogFreeCourse"].count_documents({})
    if existing and not force:
        return f"The catalog already has {existing} items, so nothing was changed (use --force to replace it)."
    now = time.time()
    db["CatalogProgram"].delete_many({})
    db["CatalogFreeCourse"].delete_many({})
    db["CatalogProgram"].insert_many([{
        "id": str(uuid.uuid4()), "order": i, "visible": True, "created_at": now,
        **{k: p.get(k, "") for k in ("title", "slug", "category", "tagline", "description", "duration")},
    } for i, p in enumerate(data["programs"], 1)])
    db["CatalogFreeCourse"].insert_many([{
        "id": str(uuid.uuid4()), "order": i, "visible": True, "created_at": now,
        **{k: c.get(k, "") for k in ("title", "category", "description")},
    } for i, c in enumerate(data["free_courses"], 1)])
    db["CatalogProgram"].create_index("slug", unique=True)
    return f"Catalog loaded: {len(data['programs'])} programs and {len(data['free_courses'])} free courses."


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data = json.loads(Path(args[0] if args else DEFAULT_FILE).read_text(encoding="utf-8"))
    slugs = [p["slug"] for p in data["programs"]]
    assert len(slugs) == len(set(slugs)), "duplicate program slugs"

    uri = os.environ.get("MONGODB_URI")
    env_file = ROOT / ".env"
    if not uri and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MONGODB_URI="):
                uri = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not uri:
        sys.exit("MONGODB_URI is not set")
    from pymongo import MongoClient
    try:
        import certifi
        client = MongoClient(uri, serverSelectionTimeoutMS=15000, tlsCAFile=certifi.where())
    except ImportError:
        client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    print(seed(client["zeptrax_db"], data, force="--force" in sys.argv))


if __name__ == "__main__":
    main()
