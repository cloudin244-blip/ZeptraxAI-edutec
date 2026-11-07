"""
Load (or update) an assessment from a JSON file into MongoDB.

    python scripts/seed_assessment.py scripts/assessments/advanced_mcq_tough.json
    python scripts/seed_assessment.py <file> --force     # replace questions even if students have started

Uses MONGODB_URI from the environment or the repo's .env file. The assessment is matched by its "code",
so running the script again updates it in place.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def seed(db, data, force=False):
    now = time.time()
    fields = {k: data[k] for k in ("title", "description", "duration_minutes", "marks_per_question", "negative_marks",
                                   "required", "audience", "show_score_to_students")}
    fields["university_ids"] = data.get("university_ids", [])
    fields["status"] = data.get("status", "published")
    existing = db["Assessment"].find_one({"code": data["code"]})
    if existing:
        assessment_id = existing["id"]
        db["Assessment"].update_one({"id": assessment_id}, {"$set": {**fields, "updated_date": now}})
    else:
        assessment_id = str(uuid.uuid4())
        db["Assessment"].insert_one({"id": assessment_id, "code": data["code"], "created_at": now, **fields})

    started = db["AssessmentAttempt"].count_documents({"assessment_id": assessment_id})
    if started and not force:
        print(f"{started} students have started this test, so its questions were left unchanged (use --force to replace them).")
        return assessment_id

    db["AssessmentQuestion"].delete_many({"assessment_id": assessment_id})
    db["AssessmentQuestion"].insert_many([{
        "id": str(uuid.uuid4()), "assessment_id": assessment_id, "order": i,
        "section": q.get("section", ""), "text": q["text"], "code": q.get("code", ""),
        "options": q["options"], "answer": q["answer"], "review": q.get("review", ""),
    } for i, q in enumerate(data["questions"], 1)])
    return assessment_id


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    for q in data["questions"]:
        assert len(q["options"]) >= 2 and 0 <= q["answer"] < len(q["options"]), q["text"][:60]

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
    db = client["zeptrax_db"]
    assessment_id = seed(db, data, force="--force" in sys.argv)
    count = db["AssessmentQuestion"].count_documents({"assessment_id": assessment_id})
    print(f"'{data['title']}' ready: {count} questions, {count * data['marks_per_question']} marks, {data['duration_minutes']} minutes (id {assessment_id})")


if __name__ == "__main__":
    main()
