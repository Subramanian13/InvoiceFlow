def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "reachable"}


def test_vendors_are_sanitized(client):
    response = client.get("/api/vendors")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 8
    assert "tax_id_fingerprint" not in payload[0]
    assert payload[0]["tax_id_last4"] == "4107"


def test_purchase_orders_include_calculated_balances(client):
    from decimal import Decimal
    response = client.get("/api/purchase-orders")
    assert response.status_code == 200
    po = next(item for item in response.json() if item["po_number"] == "PO-30010")
    assert po["authorized_total"] == "10000.00"
    assert po["committed_total"] == "7000.00"
    assert po["remaining_total"] == "3000.00"
    assert Decimal(po["lines"][0]["ordered_quantity"]) == Decimal("10")


def test_purchase_order_detail_and_not_found(client):
    orders = client.get("/api/purchase-orders").json()
    assert client.get(f"/api/purchase-orders/{orders[0]['id']}").status_code == 200
    missing = client.get("/api/purchase-orders/99999")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "PO_NOT_FOUND"
