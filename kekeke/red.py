from os import getenv
from redis import StrictRedis
redis = StrictRedis.from_url(getenv("REDIS_URL"), decode_responses=True)
