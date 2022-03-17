import os
import subprocess
import sys

import anyio
import httpx
import pytest
from httpx import ASGITransport

from prefect.orion.api.server import create_app
from prefect.utilities.testing import temporary_settings


@pytest.fixture()
def app():
    return create_app(ephemeral=True)


@pytest.fixture
async def client(app):
    """
    Yield a test client for testing the orion api
    """

    async with httpx.AsyncClient(app=app, base_url="https://test/api") as async_client:
        yield async_client


@pytest.fixture
async def client_without_exceptions(app):
    """
    Yield a test client that does not raise app exceptions.

    This is useful if you need to test e.g. 500 error responses.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(
        transport=transport, base_url="https://test/api"
    ) as async_client:
        yield async_client


@pytest.fixture(scope="session")
async def hosted_orion_api():
    """
    Runs an instance of the Orion API at a dedicated URL instead of the ephemeral
    application. Requires port 2222 to be available.

    Uses the same database as the rest of the tests.

    If built, the UI will be accessible during tests at http://localhost:2222/.

    Yields:
        The connection string
    """

    # Will connect to the same database as normal test clients
    process = await anyio.open_process(
        command=[
            "uvicorn",
            "--factory",
            "prefect.orion.api.server:create_app",
            "--host",
            "127.0.0.1",
            "--port",
            "2222",
            "--log-level",
            "info",
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    api_url = "http://localhost:2222/api"

    try:
        # Wait for the server to be ready
        async with httpx.AsyncClient() as client:
            response = None
            with anyio.move_on_after(10):
                while True:
                    try:
                        response = await client.get(api_url + "/admin/hello")
                    except httpx.ConnectError:
                        pass
                    else:
                        if response.status_code == 200:
                            break
                    await anyio.sleep(0.1)
            if response:
                response.raise_for_status()
            if not response:
                raise RuntimeError(
                    "Timed out while attempting to connect to hosted test Orion."
                )

        # Yield to the consuming tests
        yield api_url

    finally:
        # Cleanup the process
        try:
            process.terminate()
            await process.aclose()
        except Exception:
            pass  # May already be terminated

        await process.aclose()


@pytest.fixture
def use_hosted_orion(hosted_orion_api):
    """
    Sets `PREFECT_API_URL` to the test session's hosted API endpoint.
    """
    with temporary_settings(PREFECT_API_URL=hosted_orion_api):
        yield hosted_orion_api
