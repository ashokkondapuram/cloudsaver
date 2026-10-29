from workers.health import WorkerHealth


def test_worker_progress_and_dependencies_are_separate_from_liveness():
    now=[0]
    def unavailable():raise RuntimeError('private connection URL')
    health=WorkerHealth(clock=lambda:now[0],max_age=30)
    assert health.status('/health/live')[0]==200
    assert health.status('/health/ready')[0]==503
    health.touch();assert health.status('/health/ready')[0]==200
    health.dependency=unavailable
    assert health.status('/health/ready')==(503,{'status':'unavailable'})
    assert health.status('/health/live')[0]==200
    health.dependency=None;health.touch(False)
    assert health.status('/health/ready')[0]==503
    now[0]=31
    assert health.status('/health/live')[0]==503
    health.touch();health.close()
    assert health.status('/health/live')[0]==503
    assert health.status('/private')[0]==404


def test_worker_probe_server_exposes_health_without_credentials(monkeypatch):
    import httpx
    monkeypatch.setenv('CLOUDSAVER_WORKER_HEALTH_HOST','127.0.0.1')
    monkeypatch.setenv('CLOUDSAVER_WORKER_HEALTH_PORT','0')
    health=WorkerHealth().start()
    try:
        base='http://127.0.0.1:'+str(health.server.server_address[1])
        with httpx.Client(trust_env=False,timeout=2) as client:
            assert client.get(base+'/health/live').status_code==200
            assert client.get(base+'/health/ready').status_code==503
            health.touch()
            response=client.get(base+'/health/ready')
            assert response.status_code==200 and response.headers['cache-control']=='no-store'
    finally:health.close()
