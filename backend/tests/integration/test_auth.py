"""End-to-end tests for the authentication flow."""

from httpx import AsyncClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

CREDENTIALS = {"email": "ada@example.com", "password": "password123"}


async def test_register_returns_user_without_password(client: AsyncClient) -> None:
    response = await client.post(REGISTER, json=CREDENTIALS)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == CREDENTIALS["email"]
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    await client.post(REGISTER, json=CREDENTIALS)
    response = await client.post(REGISTER, json=CREDENTIALS)
    assert response.status_code == 409


async def test_login_and_access_protected_route(client: AsyncClient) -> None:
    await client.post(REGISTER, json=CREDENTIALS)

    login = await client.post(LOGIN, json=CREDENTIALS)
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = await client.get(ME, headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == CREDENTIALS["email"]


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code in (401, 403)


async def test_login_with_wrong_password_is_rejected(client: AsyncClient) -> None:
    await client.post(REGISTER, json=CREDENTIALS)
    response = await client.post(
        LOGIN, json={"email": CREDENTIALS["email"], "password": "wrong-password"}
    )
    assert response.status_code == 401


async def test_refresh_rotates_and_revokes_old_token(client: AsyncClient) -> None:
    await client.post(REGISTER, json=CREDENTIALS)
    tokens = (await client.post(LOGIN, json=CREDENTIALS)).json()

    refreshed = await client.post(
        REFRESH, json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["access_token"]

    reused = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401

    logout = await client.post(
        LOGOUT, json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert logout.status_code == 204
