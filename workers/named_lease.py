"""Redis leases for drift inspect and GitOps PR idempotency fencing."""


class NamedRedisLease:
    RELEASE = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"

    def __init__(self, url, *, client=None, ttl=30):
        import redis

        if not 1 <= ttl <= 3600:
            raise ValueError("Invalid lease TTL")
        self.ttl = ttl
        self.client = client or redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)

    def acquire(self, key: str, token: str) -> bool:
        return bool(self.client.set(key, token, nx=True, ex=self.ttl))

    def release(self, key: str, token: str) -> None:
        self.client.eval(self.RELEASE, 1, key, token)

    def close(self) -> None:
        self.client.close()


def drift_inspect_lease_key(workspace_id: str, resource_hash: str) -> str:
    return f"lease:drift_inspect:{workspace_id}:{resource_hash}"


def gitops_pr_lease_key(idempotency_key: str) -> str:
    return f"gitops:pr:{idempotency_key}"
