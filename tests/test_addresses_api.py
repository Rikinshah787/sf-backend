BASE = "/api/v1/contacts"

HOME = {"type": "home", "address": "12 Elm St", "city": "Springfield", "state": "IL", "country": "USA"}
WORK = {"type": "work", "address": "500 Office Park", "city": "Chicago", "state": "IL", "country": "USA"}


def test_create_with_multiple_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [HOME, WORK]})
    assert response.status_code == 201
    addresses = response.json()["addresses"]
    assert [a["type"] for a in addresses] == ["home", "work"]
    assert all(a["id"] > 0 for a in addresses)
    assert addresses[1]["city"] == "Chicago"


def test_addresses_default_to_empty_list(client, payload):
    body = {**payload}
    body.pop("addresses")
    assert client.post(BASE, json=body).json()["addresses"] == []


def test_address_type_is_validated(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{**HOME, "type": "vacation"}]})
    assert response.status_code == 422


def test_address_count_is_capped(client, payload):
    too_many = [{**HOME, "address": f"{i} Elm St"} for i in range(11)]
    assert client.post(BASE, json={**payload, "addresses": too_many}).status_code == 422


def test_put_replaces_the_full_address_set(client, payload):
    created = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()
    old_ids = {a["id"] for a in created["addresses"]}

    response = client.put(
        f"{BASE}/{created['id']}",
        json={**payload, "addresses": [{"type": "other", "city": "Berlin", "country": "Germany"}]},
    )
    assert response.status_code == 200
    addresses = response.json()["addresses"]
    assert len(addresses) == 1
    assert addresses[0]["type"] == "other"
    assert addresses[0]["id"] not in old_ids  # old rows were orphaned and deleted


def test_patch_without_addresses_leaves_them_untouched(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    assert len(response.json()["addresses"]) == 2


def test_patch_with_empty_list_removes_all_addresses(client, payload):
    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_deleting_a_contact_deletes_its_addresses(client, payload):
    from app.database import SessionLocal
    from app.models import Address

    contact_id = client.post(BASE, json={**payload, "addresses": [HOME, WORK]}).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204

    with SessionLocal() as db:
        assert db.query(Address).filter_by(contact_id=contact_id).count() == 0
