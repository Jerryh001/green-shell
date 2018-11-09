from os import getenv

from redis import ConnectionPool

_pool: ConnectionPool = None

def pool():
    global _pool
    if not _pool:
        _pool = ConnectionPool.from_url(getenv("REDIS_URL"), decode_responses=True)
    return _pool
