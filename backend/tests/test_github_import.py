import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import github_import
from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.project import ProjectType

from app.api.routes.github_import import (
    MAX_GITHUB_ARCHIVE_SIZE,
    _download_repository_archive,
    parse_github_repository_url,
)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/psf/requests",
            ("psf", "requests"),
        ),
        (
            " https://github.com/psf/requests.git ",
            ("psf", "requests"),
        ),
        (
            "https://github.com/OWNER/repo_name",
            ("OWNER", "repo_name"),
        ),
    ],
)
def test_parse_valid_github_repository_url(url, expected):
    assert parse_github_repository_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://github.com/psf/requests",
        "https://github.com.evil.example/psf/requests",
        "https://user:password@github.com/psf/requests",
        "https://github.com/psf/requests?tab=readme",
        "https://github.com/psf/requests#readme",
        "https://github.com/psf",
        "https://github.com/psf/requests/tree/main",
        "https://github.com/../requests",
        "https://github.com/psf/..",
        "https://gitlab.com/psf/requests",
    ],
)
def test_parse_rejects_invalid_github_repository_url(url):
    with pytest.raises(ValueError):
        parse_github_repository_url(url)


def make_client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=10.0,
        trust_env=False,
    )


def test_download_repository_archive_success():
    archive_bytes = b"PK\x03\x04fake-zip-data"

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "archived": False,
                    "default_branch": "main",
                },
            )

        if request.url.host == "codeload.github.com":
            return httpx.Response(
                200,
                content=archive_bytes,
                headers={"content-type": "application/zip"},
            )

        return httpx.Response(500)

    async def scenario():
        async with make_client(handler) as client:
            return await _download_repository_archive(
                client,
                "psf",
                "requests",
            )

    content, branch = run(scenario())

    assert content == archive_bytes
    assert branch == "main"


def test_download_encodes_special_characters_in_branch_name():
    branch_name = "feature/my branch#1"
    requested_urls = []

    def handler(request):
        requested_urls.append(str(request.url))

        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "archived": False,
                    "default_branch": branch_name,
                },
            )

        if request.url.host == "codeload.github.com":
            return httpx.Response(
                200,
                content=b"fake-archive",
            )

        return httpx.Response(500)

    async def scenario():
        async with make_client(handler) as client:
            return await _download_repository_archive(
                client,
                "owner",
                "repository",
            )

    content, returned_branch = run(scenario())

    assert content == b"fake-archive"
    assert returned_branch == branch_name

    archive_request = next(
        url
        for url in requested_urls
        if "codeload.github.com" in url
    )

    assert "/feature/my%20branch%231" in archive_request


@pytest.mark.parametrize(
    ("metadata_status", "expected_status"),
    [
        (404, 404),
        (403, 429),
        (500, 502),
    ],
)
def test_download_repository_archive_maps_github_metadata_errors(
    metadata_status,
    expected_status,
):
    def handler(request):
        return httpx.Response(
            metadata_status,
            json={"message": "failure"},
        )

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "psf",
                "requests",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == expected_status


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "private": True,
            "archived": False,
            "default_branch": "main",
        },
        {
            "private": False,
            "archived": True,
            "default_branch": "main",
        },
    ],
)
def test_download_rejects_private_or_archived_repositories(metadata):
    def handler(request):
        return httpx.Response(200, json=metadata)

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "owner",
                "repo",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == 400


@pytest.mark.parametrize(
    "metadata",
    [
        {"private": False, "archived": False},
        {
            "private": False,
            "archived": False,
            "default_branch": "",
        },
        {
            "private": False,
            "archived": False,
            "default_branch": None,
        },
    ],
)
def test_download_rejects_invalid_repository_metadata(metadata):
    def handler(request):
        return httpx.Response(200, json=metadata)

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "owner",
                "repo",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == 502


def test_download_rejects_archive_when_content_length_exceeds_limit():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "archived": False,
                    "default_branch": "main",
                },
            )

        return httpx.Response(
            200,
            content=b"",
            headers={
                "content-length": str(
                    MAX_GITHUB_ARCHIVE_SIZE + 1
                ),
            },
        )

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "owner",
                "repo",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == 413


def test_download_rejects_archive_when_streamed_bytes_exceed_limit():
    oversized_content = b"x" * (
        MAX_GITHUB_ARCHIVE_SIZE + 1
    )

    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "archived": False,
                    "default_branch": "main",
                },
            )

        return httpx.Response(
            200,
            content=oversized_content,
        )

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "owner",
                "repo",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == 413


def test_download_rejects_missing_default_branch_archive():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "private": False,
                    "archived": False,
                    "default_branch": "main",
                },
            )

        return httpx.Response(404)

    async def scenario():
        async with make_client(handler) as client:
            await _download_repository_archive(
                client,
                "owner",
                "repo",
            )

    with pytest.raises(HTTPException) as error:
        run(scenario())

    assert error.value.status_code == 404


def test_github_import_rejects_generated_project_without_network_access(
    monkeypatch,
):
    app = FastAPI()
    app.include_router(github_import.router)

    user = SimpleNamespace(id=uuid4())
    project_id = uuid4()

    generated_project = SimpleNamespace(
        id=project_id,
        project_type=ProjectType.GENERATED,
    )

    class FakeDB:
        pass

    db = FakeDB()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db

    monkeypatch.setattr(
        github_import,
        "get_project",
        lambda *args, **kwargs: generated_project,
    )

    network_calls = []

    def forbidden_async_client(*args, **kwargs):
        network_calls.append(True)
        raise AssertionError(
            "GitHub must not be contacted for generated projects."
        )

    monkeypatch.setattr(
        github_import.httpx,
        "AsyncClient",
        forbidden_async_client,
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/projects/{project_id}/import-github",
                json={
                    "repository_url": (
                        "https://github.com/example/repository"
                    )
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400

    assert response.json()["detail"] == (
        "GitHub repositories can only be imported "
        "into uploaded projects."
    )

    assert network_calls == []