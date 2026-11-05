def test_inventory_query_constant_does_not_load_settings():
    from app.scanner import INVENTORY_QUERY, inventory_query_body

    assert INVENTORY_QUERY == inventory_query_body()
    assert INVENTORY_QUERY.startswith('Resources | where isnotempty(id)')
