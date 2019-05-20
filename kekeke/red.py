from os import getenv

from redis import Redis

redis = Redis.from_url(getenv("REDISCLOUD_URL"), decode_responses=True)
