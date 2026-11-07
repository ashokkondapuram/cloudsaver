from app.v150_analysis import create_router


def test_verified_dependency_strings_surface_in_auto_scenarios():
    scan = {
        "scan_id": "00000000-0000-4000-8000-000000000001",
        "timestamp": "2026-11-07T00:00:00+00:00",
        "status": "completed",
        "inventory": [
            {
                "resource_id": "a",
                "evidence": {"verified_dependencies": ["b"]},
            },
            {"resource_id": "b", "evidence": {}},
        ],
        "findings": [],
    }

    class Store:
        def get(self, _tenant, scan_id):
            return scan if scan_id == scan["scan_id"] else None

    class Finance:
        def attach(self, _tenant, payload):
            return payload

    router = create_router(Store(), lambda: {"tenant_id": "t"}, Finance())
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/auto-scenarios"))
    payload = route.endpoint(scan_id=scan["scan_id"], tenant={"tenant_id": "t"})
    items = payload["engines"]["topology"]["items"]
    assert items and items[0]["dependencies"][0]["to_resource_id"] == "b"


def test_network_engine_observes_egress_bytes_per_sec():
    scan = {
        "scan_id": "00000000-0000-4000-8000-000000000002",
        "timestamp": "2026-11-07T00:00:00+00:00",
        "status": "completed",
        "inventory": [
            {"resource_id": "vm-1", "evidence": {"network_egress_bytes_per_sec": 125000.0}},
        ],
        "findings": [],
    }

    class Store:
        def get(self, _tenant, scan_id):
            return scan if scan_id == scan["scan_id"] else None

    class Finance:
        def attach(self, _tenant, payload):
            return payload

    router = create_router(Store(), lambda: {"tenant_id": "t"}, Finance())
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/auto-scenarios"))
    payload = route.endpoint(scan_id=scan["scan_id"], tenant={"tenant_id": "t"})
    network = payload["engines"]["network"]
    assert network["status"] == "observed_signals"
    assert network["items"][0]["observations"]["network_egress_bytes_per_sec"] == 125000.0
    assert payload["engines"]["network"]["savings_usd"] is None
