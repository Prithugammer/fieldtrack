"""User management (Admin only): creation, updates, protected fields, filters, active state."""

import pytest

from extensions import db
from models import User
from tests.conftest import PASSWORD, login


def new_user(**changes):
    body = {
        "full_name": "Maya Lama",
        "email": "maya.lama@test.com",
        "phone": "+977-9841-0199",
        "role": "Dispatcher",
        "password": "Sup3rSecret!",
    }
    body.update(changes)
    return body


def uid(email):
    return User.query.filter_by(email=email).one().user_id


# ---- who may do what -----------------------------------------------------------------------------


def test_only_admins_create_or_edit_users(client, dispatcher_headers, supervisor_headers):
    for headers in (dispatcher_headers, supervisor_headers):
        assert client.post("/api/users", json=new_user(), headers=headers).status_code == 403
        assert client.patch("/api/users/1", json={}, headers=headers).status_code == 403
    assert User.query.filter_by(email="maya.lama@test.com").count() == 0


def test_every_staff_role_can_list_users(client, dispatcher_headers, supervisor_headers):
    for headers in (dispatcher_headers, supervisor_headers):
        users = client.get("/api/users", headers=headers).get_json()["users"]
        assert len(users) == 5 and all("password_hash" not in u for u in users)


# ---- create --------------------------------------------------------------------------------------


def test_admin_creates_a_staff_user_who_can_log_in(client, admin_headers):
    res = client.post("/api/users", json=new_user(), headers=admin_headers)
    assert res.status_code == 201
    user = res.get_json()["user"]
    assert user["role"] == "Dispatcher" and user["is_active"] is True and "password" not in user
    assert (
        client.post(
            "/api/auth/login", json={"email": "maya.lama@test.com", "password": "Sup3rSecret!"}
        ).status_code
        == 200
    )


def test_email_is_normalised_and_must_be_unique(client, admin_headers):
    ok = client.post(
        "/api/users", json=new_user(email="  Maya.Lama@TEST.com "), headers=admin_headers
    )
    assert ok.get_json()["user"]["email"] == "maya.lama@test.com"
    dup = client.post(
        "/api/users", json=new_user(email="MAYA.LAMA@test.com"), headers=admin_headers
    )
    assert dup.status_code == 409 and dup.get_json()["field"] == "email"


def test_a_worker_needs_a_trade_but_no_password(client, admin_headers):
    body = new_user(role="Worker", email="w1@test.com", password=None, trade="Welder")
    res = client.post("/api/users", json=body, headers=admin_headers)
    assert res.status_code == 201 and res.get_json()["user"]["trade"] == "Welder"
    assert User.query.filter_by(email="w1@test.com").one().password_hash is None
    no_trade = new_user(role="Worker", email="w2@test.com", password=None)
    res = client.post("/api/users", json=no_trade, headers=admin_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "trade"


def test_a_worker_given_a_password_still_cannot_log_in(client, admin_headers):
    body = new_user(role="Worker", email="w3@test.com", trade="Welder")
    assert client.post("/api/users", json=body, headers=admin_headers).status_code == 201
    assert User.query.filter_by(email="w3@test.com").one().password_hash is None
    res = client.post("/api/auth/login", json={"email": "w3@test.com", "password": "Sup3rSecret!"})
    assert res.status_code == 401


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"full_name": ""}, "full_name"),
        ({"full_name": "A"}, "full_name"),
        ({"full_name": "x" * 101}, "full_name"),
        ({"email": "not-an-email"}, "email"),
        ({"email": None}, "email"),
        ({"phone": "abc"}, "phone"),
        ({"role": "Boss"}, "role"),
        ({"role": None}, "role"),
        ({"password": "short"}, "password"),
        ({"password": None}, "password"),
        ({"password": 12345678}, "password"),
        ({"full_name": ["list"]}, "full_name"),
    ],
)
def test_invalid_user_fields_are_rejected_without_creating_anything(
    client, admin_headers, changes, field
):
    before = User.query.count()
    res = client.post("/api/users", json=new_user(**changes), headers=admin_headers)
    assert res.status_code == 400 and res.get_json()["field"] == field
    assert User.query.count() == before


# ---- list filters --------------------------------------------------------------------------------


def test_list_filters_by_role_and_active(client, admin_headers):
    workers = client.get("/api/users?role=Worker", headers=admin_headers).get_json()["users"]
    assert {u["role"] for u in workers} == {"Worker"} and len(workers) == 2
    User.query.filter_by(email="ben@test.com").one().is_active = False
    db.session.commit()
    active = client.get("/api/users?role=Worker&active=true", headers=admin_headers)
    assert [u["email"] for u in active.get_json()["users"]] == ["marcus@test.com"]
    inactive = client.get("/api/users?active=false", headers=admin_headers).get_json()["users"]
    assert [u["email"] for u in inactive] == ["ben@test.com"]
    assert client.get("/api/users?role=Boss", headers=admin_headers).status_code == 400
    assert client.get("/api/users?active=maybe", headers=admin_headers).status_code == 400


# ---- update --------------------------------------------------------------------------------------


def test_update_changes_only_the_fields_sent(client, admin_headers):
    target = uid("dispatch@test.com")
    res = client.patch(
        f"/api/users/{target}",
        json={"full_name": "Renamed Person", "phone": "+977-1-5551234"},
        headers=admin_headers,
    )
    user = res.get_json()["user"]
    assert res.status_code == 200 and user["full_name"] == "Renamed Person"
    assert user["email"] == "dispatch@test.com" and user["role"] == "Dispatcher"


def test_update_unknown_or_missing_user_is_404(client, admin_headers):
    assert client.patch("/api/users/987654", json={}, headers=admin_headers).status_code == 404
    assert client.patch("/api/users/0", json={}, headers=admin_headers).status_code == 404


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"full_name": "A"}, "full_name"),
        ({"phone": "call me"}, "phone"),
        ({"email": "bad"}, "email"),
        ({"role": "Boss"}, "role"),
        ({"is_active": "maybe"}, "is_active"),
        ({"password": "short"}, "password"),
        ({"password": "x" * 80}, "password"),
    ],
)
def test_invalid_update_fields_are_400_and_change_nothing(client, admin_headers, changes, field):
    target = uid("dispatch@test.com")
    before = db.session.get(User, target).to_dict()
    res = client.patch(f"/api/users/{target}", json=changes, headers=admin_headers)
    assert res.status_code == 400 and res.get_json()["field"] == field
    db.session.expire_all()
    assert db.session.get(User, target).to_dict() == before


def test_email_change_cannot_take_another_users_address(client, admin_headers):
    res = client.patch(
        f"/api/users/{uid('dispatch@test.com')}",
        json={"email": "super@test.com"},
        headers=admin_headers,
    )
    assert res.status_code == 409 and res.get_json()["field"] == "email"
    same = client.patch(
        f"/api/users/{uid('dispatch@test.com')}",
        json={"email": "DISPATCH@test.com"},
        headers=admin_headers,
    )
    assert same.status_code == 200  # keeping your own address is not a clash


def test_password_reset_replaces_the_hash_and_blank_means_unchanged(client, admin_headers):
    target = uid("dispatch@test.com")
    old_hash = db.session.get(User, target).password_hash
    client.patch(f"/api/users/{target}", json={"password": ""}, headers=admin_headers)
    db.session.expire_all()
    assert db.session.get(User, target).password_hash == old_hash
    client.patch(f"/api/users/{target}", json={"password": "BrandNew#123"}, headers=admin_headers)
    db.session.expire_all()
    assert db.session.get(User, target).password_hash != old_hash
    assert (
        client.post(
            "/api/auth/login", json={"email": "dispatch@test.com", "password": "BrandNew#123"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "dispatch@test.com", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_an_admin_cannot_demote_or_deactivate_themselves(client, admin_headers):
    me = uid("admin@test.com")
    demote = client.patch(f"/api/users/{me}", json={"role": "Dispatcher"}, headers=admin_headers)
    assert demote.status_code == 409 and demote.get_json()["field"] == "role"
    off = client.patch(f"/api/users/{me}", json={"is_active": False}, headers=admin_headers)
    assert off.status_code == 409 and off.get_json()["field"] == "is_active"
    assert db.session.get(User, me).role == "Admin" and db.session.get(User, me).is_active


def test_deactivating_a_user_blocks_login_and_reactivating_restores_it(client, admin_headers):
    target = uid("dispatch@test.com")
    old_token = login(client, "dispatch@test.com")
    off = client.patch(f"/api/users/{target}", json={"is_active": False}, headers=admin_headers)
    assert off.get_json()["user"]["is_active"] is False
    creds = {"email": "dispatch@test.com", "password": PASSWORD}
    assert client.post("/api/auth/login", json=creds).status_code == 403
    assert client.get("/api/jobs", headers=old_token).status_code == 403
    client.patch(f"/api/users/{target}", json={"is_active": "true"}, headers=admin_headers)
    assert client.post("/api/auth/login", json=creds).status_code == 200


def test_role_changes_enforce_the_cross_field_rules(client, admin_headers):
    worker = uid("ben@test.com")
    res = client.patch(f"/api/users/{worker}", json={"role": "Dispatcher"}, headers=admin_headers)
    assert res.status_code == 400 and res.get_json()["field"] == "password"  # staff need a login
    ok = client.patch(
        f"/api/users/{worker}",
        json={"role": "Dispatcher", "password": "Prom0ted!Pass"},
        headers=admin_headers,
    )
    assert ok.status_code == 200
    staff = uid("dispatch@test.com")
    res = client.patch(
        f"/api/users/{staff}", json={"role": "Worker", "trade": ""}, headers=admin_headers
    )
    assert res.status_code == 400 and res.get_json()["field"] == "trade"
    assert db.session.get(User, staff).role == "Dispatcher"  # the failed change was not committed
    client.patch(f"/api/users/{staff}", json={"trade": "Laborer"}, headers=admin_headers)


def test_protected_fields_cannot_be_set_through_the_update(client, admin_headers):
    target = uid("dispatch@test.com")
    res = client.patch(
        f"/api/users/{target}",
        json={"user_id": 999, "password_hash": "x", "created_by": 1},
        headers=admin_headers,
    )
    assert res.status_code == 200
    user = db.session.get(User, target)
    assert user.user_id == target and user.password_hash.startswith("$2")
