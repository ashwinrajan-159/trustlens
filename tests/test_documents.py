"""Document upload/list/download tests (magic-byte validation + versioning)."""
import pytest

_PDF = b"%PDF-1.4\n%fake pdf body for testing\n%%EOF"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _headers(client, email="docuser@example.com"):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "Doc"},
        )
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _make_app(client, headers):
    return (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=headers,
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_upload_pdf_succeeds_and_stores_object(client):
    h = await _headers(client)
    app_id = await _make_app(client, h)
    r = await client.post(
        f"/api/v1/applications/{app_id}/documents",
        data={"document_type": "PAN"},
        files={"file": ("pan.pdf", _PDF, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "QUEUED"
    assert body["version"] == 1
    assert body["content_type"] == "application/pdf"
    assert len(client.fake_storage.objects) == 1


@pytest.mark.asyncio
async def test_upload_rejects_content_type_mismatch_by_magic_bytes(client):
    h = await _headers(client)
    app_id = await _make_app(client, h)
    # Claims PDF but the bytes are a PNG — magic-byte sniffing accepts as PNG (allowed),
    # but a text blob claiming PDF must be rejected.
    r = await client.post(
        f"/api/v1/applications/{app_id}/documents",
        data={"document_type": "PAN"},
        files={"file": ("evil.pdf", b"not a real document", "application/pdf")},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_reupload_supersedes_version(client):
    h = await _headers(client)
    app_id = await _make_app(client, h)
    url = f"/api/v1/applications/{app_id}/documents"
    await client.post(url, data={"document_type": "PAN"},
                      files={"file": ("v1.pdf", _PDF, "application/pdf")}, headers=h)
    r2 = await client.post(url, data={"document_type": "PAN"},
                           files={"file": ("v2.png", _PNG, "image/png")}, headers=h)
    assert r2.status_code == 201
    assert r2.json()["version"] == 2

    listing = (await client.get(url, headers=h)).json()
    current = [d for d in listing if d["is_current_version"]]
    assert len(current) == 1
    assert current[0]["version"] == 2


@pytest.mark.asyncio
async def test_download_returns_presigned_url(client):
    h = await _headers(client)
    app_id = await _make_app(client, h)
    doc_id = (
        await client.post(
            f"/api/v1/applications/{app_id}/documents",
            data={"document_type": "PAN"},
            files={"file": ("pan.pdf", _PDF, "application/pdf")},
            headers=h,
        )
    ).json()["id"]
    r = await client.get(f"/api/v1/documents/{doc_id}/download", headers=h)
    assert r.status_code == 200
    assert r.json()["url"].startswith("https://fake-storage.local/")


@pytest.mark.asyncio
async def test_cannot_upload_to_others_application(client):
    h1 = await _headers(client, "owner@example.com")
    app_id = await _make_app(client, h1)
    h2 = await _headers(client, "intruder@example.com")
    r = await client.post(
        f"/api/v1/applications/{app_id}/documents",
        data={"document_type": "PAN"},
        files={"file": ("pan.pdf", _PDF, "application/pdf")},
        headers=h2,
    )
    assert r.status_code == 403
