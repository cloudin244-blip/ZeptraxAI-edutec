"""
Website catalog: the Masters programs and free courses shown on the landing page, /programs, /programs/<slug>,
/courses and the footer. Anyone can read the visible catalog (GET /api/catalog); only the super admin can change
it (/api/portal/catalog/...).

While both collections are empty, GET /api/catalog returns nulls and the site keeps its built-in lists.
"""
import json
import re
import time
import uuid

import _db_router as core

KINDS = {
    "programs": {
        "collection": "CatalogProgram",
        "fields": {"title": 150, "slug": 100, "category": 60, "tagline": 200, "description": 2000, "duration": 40},
    },
    "free-courses": {
        "collection": "CatalogFreeCourse",
        "fields": {"title": 150, "category": 60, "description": 500},
    },
}
PUBLIC_FIELDS = {
    "programs": ("title", "slug", "category", "tagline", "description", "duration"),
    "free-courses": ("title", "category", "description"),
}


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def slugify(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:100]


def ordered(db, kind, visible_only=False):
    query = {"visible": True} if visible_only else {}
    docs = db[KINDS[kind]["collection"]].find(query).sort("order", 1)
    if visible_only:
        return [{f: d.get(f, "") for f in PUBLIC_FIELDS[kind]} for d in docs]
    return [{"id": d["id"], "visible": d.get("visible", True), "order": d.get("order", 0),
             **{f: d.get(f, "") for f in KINDS[kind]["fields"]}} for d in docs]


def public_catalog(db):
    """What the website shows. Nulls mean 'not set up yet: keep the built-in lists'."""
    if db is None:
        return ok({"programs": None, "free_courses": None})
    has_programs = db["CatalogProgram"].count_documents({}) > 0
    has_free = db["CatalogFreeCourse"].count_documents({}) > 0
    return ok({
        "programs": ordered(db, "programs", True) if has_programs else None,
        "free_courses": ordered(db, "free-courses", True) if has_free else None,
    })


def parse(body):
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def validate(db, kind, data, existing=None):
    fields = KINDS[kind]["fields"]
    values = {f: clean(data[f], limit) for f, limit in fields.items() if f in data}
    if "visible" in data:
        values["visible"] = bool(data["visible"])
    if existing is None or "title" in values:
        if not values.get("title"):
            return None, "Title is required"
    if kind == "programs":
        if existing is None and not values.get("slug"):
            values["slug"] = slugify(values["title"])
        if "slug" in values:
            values["slug"] = slugify(values["slug"])
            if not values["slug"]:
                return None, "Web address (slug) needs letters or numbers"
            clash = db["CatalogProgram"].find_one({"slug": values["slug"]})
            if clash and (existing is None or clash["id"] != existing["id"]):
                return None, f"Another program already uses the address /programs/{values['slug']}"
    return values, None


def create(db, kind, body, user):
    data = parse(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = validate(db, kind, data)
    if problem:
        return error(400, problem)
    coll = db[KINDS[kind]["collection"]]
    last = list(coll.find({}, {"order": 1}).sort("order", -1).limit(1))
    doc = {f: "" for f in KINDS[kind]["fields"]}
    doc.update({"id": str(uuid.uuid4()), "visible": True, "order": (last[0].get("order", 0) + 1) if last else 1,
                "created_by": user.get("email"), "created_at": time.time(), **values})
    coll.insert_one(doc)
    return ok({"item": next(i for i in ordered(db, kind) if i["id"] == doc["id"])}, 201)


def update(db, kind, item_id, body, user):
    coll = db[KINDS[kind]["collection"]]
    existing = coll.find_one({"id": item_id})
    if not existing:
        return error(404, "Not found")
    data = parse(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = validate(db, kind, data, existing)
    if problem:
        return error(400, problem)
    coll.update_one({"id": item_id}, {"$set": {**values, "updated_by": user.get("email"), "updated_date": time.time()}})
    return ok({"item": next(i for i in ordered(db, kind) if i["id"] == item_id)})


def delete(db, kind, item_id):
    result = db[KINDS[kind]["collection"]].delete_one({"id": item_id})
    return ok({"deleted": True}) if result.deleted_count else error(404, "Not found")


def reorder(db, kind, body):
    data = parse(body) or {}
    ids = data.get("ids")
    coll = db[KINDS[kind]["collection"]]
    current = [d["id"] for d in coll.find({}, {"id": 1})]
    if not isinstance(ids, list) or sorted(ids) != sorted(current):
        return error(400, "The list changed while you were editing. Reload and try again.")
    for position, item_id in enumerate(ids, 1):
        coll.update_one({"id": item_id}, {"$set": {"order": position}})
    return ok({"items": ordered(db, kind)})


def handle(db, method, path, body, user):
    """Routes below /api/portal/catalog; super admin only"""
    if not core.is_super_admin(user):
        return error(403, "Only the super admin can change the website catalog")
    if path == "/catalog" and method == "GET":
        return ok({"programs": ordered(db, "programs"), "free_courses": ordered(db, "free-courses")})
    match = re.fullmatch(r"/catalog/(programs|free-courses)(?:/([\w-]+))?", path)
    if not match:
        return error(404, "Not found")
    kind, item = match.groups()
    if item is None and method == "POST":
        return create(db, kind, body, user)
    if item == "reorder" and method == "POST":
        return reorder(db, kind, body)
    if item and method == "PUT":
        return update(db, kind, item, body, user)
    if item and method == "DELETE":
        return delete(db, kind, item)
    return error(405, "Not allowed")
