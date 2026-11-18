"""Helpers for the verify_*.py harnesses: R2 TEST bucket only (refuses any bucket whose name lacks "test")."""
import requests

VERIFY_PREFIX = "checksphere/verify/"


def _guard():
    import r2_storage
    if "test" not in (r2_storage.bucket() or "").lower():
        raise RuntimeError("test helpers only run against the R2 test bucket")
    return r2_storage


def list_keys(prefix: str) -> list[str]:
    r2 = _guard()
    c, keys, token = r2.client(), [], None
    while True:
        kw = {"Bucket": r2.bucket(), "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        res = c.list_objects_v2(**kw)
        keys += [o["Key"] for o in res.get("Contents", [])]
        if not res.get("IsTruncated"):
            return keys
        token = res["NextContinuationToken"]


def sweep(prefix: str = VERIFY_PREFIX) -> int:
    """Delete every test object under the harness folder (incl. start-up backups). Returns how many are left."""
    if not prefix.startswith("checksphere/verify"):
        raise RuntimeError("sweep is limited to checksphere/verify* test folders")
    r2 = _guard()
    for k in list_keys(prefix):
        r2.client().delete_object(Bucket=r2.bucket(), Key=k)
    return len(list_keys(prefix))


def unsigned_status(key: str) -> int:
    """HTTP status of an anonymous (unsigned) GET for the object: must be refused for a private bucket."""
    r2 = _guard()
    return requests.get(f"{r2.endpoint()}/{r2.bucket()}/{key}", timeout=30).status_code
