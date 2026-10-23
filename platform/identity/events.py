"""Redis pub/sub evictions, kept during 1.0.x next to the cache_events long poll. IDs only, never key material."""
import json
import logging

from identity.config import env

CHANNEL = 'cloudsaver:identity:events'
logger = logging.getLogger('platform.identity')


def redis_url():
    return env('REDIS_URL', 'redis://platform-redis:6379/0', legacy='CLOUDSAVER_IDENTITY_REDIS_URL')


class MemoryEvents:
    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(dict(message))


class RedisEvents:
    def __init__(self, url=None):
        import redis
        self.client = redis.from_url(url or redis_url(), socket_connect_timeout=2, socket_timeout=2)

    def publish(self, message):
        try:
            self.client.publish(CHANNEL, json.dumps(message, separators=(',', ':')))
        except Exception:
            # The long poll and cache TTLs (at most 30 seconds) still bound propagation when Redis is down.
            logger.warning('Identity eviction could not be published event=%s', message.get('event'))
