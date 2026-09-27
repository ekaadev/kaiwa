"""Run with TEST_DATABASE_URL pointing to a disposable PostgreSQL database."""

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import AllocationCounter, Base, Participant
from app.study import enroll


def test_concurrent_postgres_enrollment_stays_balanced():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = create_engine(url, pool_size=8, max_overflow=4)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(AllocationCounter(id=1, fixed_first=0, adaptive_first=0))
            db.commit()

        def create_one(_):
            with Session(engine) as db:
                return enroll(db, "test-only").participant.id

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(create_one, range(24)))
        assert len(set(ids)) == 24
        with Session(engine) as db:
            groups = Counter(db.scalars(select(Participant.order)).all())
            assert groups == {"AB": 12, "BA": 12}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
