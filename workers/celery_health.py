"""Consumer/beat progress probes. Import registers hooks without opening any sockets."""
import atexit
import os
from celery.beat import PersistentScheduler
from celery.signals import heartbeat_sent, worker_ready, worker_shutdown
from workers.health import WorkerHealth

_health=None


def broker_probe():
    import redis
    with redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/1'),socket_connect_timeout=2,socket_timeout=2) as client:
        client.ping()


def start(max_age):
    global _health
    if _health is None:
        _health=WorkerHealth(max_age=max_age,dependency=broker_probe).start()
        atexit.register(_health.close)
    _health.touch()


@worker_ready.connect
def ready(**kwargs):start(60)


@heartbeat_sent.connect
def heartbeat(**kwargs):
    if _health:_health.touch()


@worker_shutdown.connect
def stopped(**kwargs):
    if _health:_health.stopping=True


class HealthScheduler(PersistentScheduler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not kwargs.get('lazy'):start(max(600,self.max_interval*2))

    def tick(self,*args,**kwargs):
        result=super().tick(*args,**kwargs)
        if _health:_health.touch()
        return result
