from pymongo import ASCENDING, MongoClient

from app.config import Settings


def create_mongo_database(settings: Settings):
    client = MongoClient(settings.mongo_uri)
    return client[settings.database_name]


def ensure_indexes(db) -> None:
    db.jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    db.jobs.create_index([("worker_id", ASCENDING), ("status", ASCENDING)])
    db.jobs.create_index([("notebook_id", ASCENDING)])
    db.workers.create_index([("status", ASCENDING), ("heartbeat_at", ASCENDING)])
    db.artifacts.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])
    db.events.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])
    db.events.create_index([("level", ASCENDING), ("created_at", ASCENDING)])
