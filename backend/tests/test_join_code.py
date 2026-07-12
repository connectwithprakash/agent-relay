"""Tests for the legacy pairing capability and secure participant enrollment."""


class TestCreateRelayHasJoinCode:
    def test_create_relay_has_high_entropy_pairing_capability(self, client):
        response = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True})
        assert response.status_code == 200
        code = response.json()["join_code"]
        assert len(code) == 48
        assert code.isalnum()
        assert code == code.upper()


class TestLegacyJoinByCode:
    def test_disabled_by_default(self, client, monkeypatch):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"]}).json()
        monkeypatch.setattr(
            "app.routes.registry.settings.allow_legacy_shared_pairing", False
        )
        response = client.post(
            f"/relays/join/{created['join_code']}", params={"agent_name": "bob"}
        )
        assert response.status_code == 410
        assert "named invitation" in response.json()["detail"]

    def test_approved_unpaired_participant_can_pair_once(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        response = client.post(f"/relays/join/{created['join_code']}", params={"agent_name": "bob"})
        assert response.status_code == 200
        assert response.json()["relay_id"] == created["relay_id"]
        assert response.json()["token"]

    def test_unapproved_participant_cannot_mutate_roster(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        response = client.post(f"/relays/join/{created['join_code']}", params={"agent_name": "charlie"})
        assert response.status_code == 403
        state = client.get(f"/relays/{created['relay_id']}").json()
        assert state["agent_names"] == ["alice", "bob"]

    def test_existing_credential_is_not_revealed_again(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        response = client.post(f"/relays/join/{created['join_code']}", params={"agent_name": "alice"})
        assert response.status_code == 409

    def test_join_by_code_invalid(self, client):
        response = client.post("/relays/join/ZZZZZZ", params={"agent_name": "alice"})
        assert response.status_code == 404

    def test_join_code_case_insensitive_for_approved_participant(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        response = client.post(f"/relays/join/{created['join_code'].lower()}", params={"agent_name": "bob"})
        assert response.status_code == 200


class TestGetRelayByCode:
    def test_get_relay_by_code(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        response = client.get(f"/relays/code/{created['join_code']}")
        assert response.status_code == 200
        assert response.json()["relay_id"] == created["relay_id"]

    def test_get_relay_by_code_invalid(self, client):
        assert client.get("/relays/code/XXXXXX").status_code == 404

    def test_get_relay_by_code_case_insensitive(self, client):
        created = client.post("/relays", json={"agent_names": ["alice", "bob"], "is_public": True}).json()
        assert client.get(f"/relays/code/{created['join_code'].lower()}").status_code == 200
