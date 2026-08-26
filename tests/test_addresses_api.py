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


def test_legacy_flat_address_columns_are_migrated(client):
    """A database from before this change is backfilled into the addresses table."""
    from sqlalchemy import inspect, text

    from app.database import Base, SessionLocal, engine, init_db
    from app.models import Contact

    # Recreate the pre-migration schema: flat postal columns, no addresses table.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE contacts ("
                " id INTEGER PRIMARY KEY,"
                " first_name VARCHAR(100) NOT NULL, last_name VARCHAR(100) NOT NULL,"
                " email VARCHAR(320) NOT NULL UNIQUE, phone VARCHAR(40),"
                " company VARCHAR(200), job_title VARCHAR(200),"
                " address VARCHAR(300), city VARCHAR(120), state VARCHAR(120),"
                " postal_code VARCHAR(20), country VARCHAR(120), notes TEXT, photo TEXT,"
                " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                " updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO contacts (id, first_name, last_name, email, address, city, country)"
                " VALUES (1, 'Ada', 'Lovelace', 'ada@example.com', '1 Market St', 'San Francisco', 'USA')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO contacts (id, first_name, last_name, email)"
                " VALUES (2, 'Grace', 'Hopper', 'grace@example.com')"
            )
        )

    init_db()  # creates the addresses table, backfills, drops the legacy columns

    with SessionLocal() as db:
        migrated = db.get(Contact, 1)
        assert [(a.type, a.address, a.city) for a in migrated.addresses] == [
            ("home", "1 Market St", "San Francisco")
        ]
        assert db.get(Contact, 2).addresses == []

    remaining = {column["name"] for column in inspect(engine).get_columns("contacts")}
    assert not remaining & {"address", "city", "state", "postal_code", "country"}

    init_db()  # idempotent: running the migration again must not duplicate rows
    with SessionLocal() as db:
        assert len(db.get(Contact, 1).addresses) == 1
