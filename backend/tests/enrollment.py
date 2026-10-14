import uuid


def new_key() -> dict[str, str]:
    """Fresh enrollment Idempotency-Key header; each call represents a new enrollment attempt."""
    return {"Idempotency-Key": uuid.uuid4().hex}


def enroll_request(client, key=None):
    """POST a consenting enrollment; pass `key` to replay the same attempt."""
    headers = {"Idempotency-Key": key} if key else new_key()
    return client.post("/v1/study/participants", json={"accepted": True}, headers=headers)
