"""Script HA onboarding + long-lived token minting for CI (ha-api-notes §1.2).

A fresh Home Assistant container starts un-onboarded. This drives the onboarding
REST flow (create the owner user, complete the core_config/analytics/integration
steps), then mints a long-lived access token over the WebSocket — exactly the
capture recorded in docs/internals/ha-api-notes.md §1.2. The token is written to the path
given as argv[1] (and echoed as ``HASSLE_TEST_HA_TOKEN=<token>`` on stdout so a
workflow can append it to ``$GITHUB_ENV``).

Usage:  python onboard_ha.py <token_output_path> [base_url]
Only depends on aiohttp (already a hassle-core dependency).
"""

from __future__ import annotations

import asyncio
import sys

import aiohttp


async def _wait_until_up(session: aiohttp.ClientSession, base: str, *, timeout: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            async with session.get(f"{base}/api/onboarding") as resp:
                if resp.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        if loop.time() >= deadline:
            raise SystemExit(f"HA did not come up at {base} within {timeout}s")
        await asyncio.sleep(2.0)


async def main(token_path: str, base: str) -> None:
    ws_url = base.replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as session:
        await _wait_until_up(session, base, timeout=180.0)

        async with session.post(
            f"{base}/api/onboarding/users",
            json={
                "client_id": f"{base}/",
                "name": "Hassle CI",
                "username": "hassle",
                "password": "hassle-ci-password",
                "language": "en",
            },
        ) as resp:
            resp.raise_for_status()
            auth_code = (await resp.json())["auth_code"]

        async with session.post(
            f"{base}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": f"{base}/",
            },
        ) as resp:
            resp.raise_for_status()
            access_token = (await resp.json())["access_token"]

        headers = {"Authorization": f"Bearer {access_token}"}
        for step in ("core_config", "analytics", "integration"):
            async with session.post(
                f"{base}/api/onboarding/{step}", json={"client_id": f"{base}/"}, headers=headers
            ):
                pass  # best-effort: some steps 200, some no-op once done

        async with session.ws_connect(ws_url) as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": access_token})
            await ws.receive_json()  # auth_ok
            await ws.send_json(
                {
                    "id": 1,
                    "type": "auth/long_lived_access_token",
                    "client_name": "hassle-ci",
                    "lifespan": 3650,
                }
            )
            result = await ws.receive_json()
            long_lived = result["result"]

    with open(token_path, "w", encoding="utf-8") as handle:
        handle.write(long_lived)
    print(f"HASSLE_TEST_HA_TOKEN={long_lived}")


if __name__ == "__main__":
    token_out = sys.argv[1] if len(sys.argv) > 1 else "ha_token.txt"
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8123"
    asyncio.run(main(token_out, base_url))
