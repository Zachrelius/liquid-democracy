"""Phase 75b — Smart Import (AI agenda → proposals).

The Anthropic API is mocked in ALL tests (no real network calls). Coverage
(spec §75b tests):
- Text input well-formed → items with proposals, topics resolved, reasoning.
- PDF input → pdfplumber extracts → same pipeline (API mocked).
- Topic resolution: known names resolve; unknown name → per-item field error.
- meeting_date → voting_end_date on each draft; omitted → null.
- Instructions pass-through into the prompt (mock inspection).
- Malformed LLM response → 200, empty items, warning.
- LLM timeout/transport error → 200, empty items, warning.
- No API key → 503.
- PDF extraction failure → 422; empty text → 422.
- Cap enforcement (text > 100KB → 422).
- Auth: member without proposal.create → 403.
- No Proposal rows written in any case.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import smart_import
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    """Configure a fake key for all tests except the explicit no-key test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _user(db, username):
    u = models.User(username=username, display_name=username, password_hash=_DUMMY_HASH,
                    email=f"{username}@t.ex", email_verified=True)
    db.add(u)
    db.flush()
    return u


def _org(db, slug):
    o = models.Organization(name=slug.title(), slug=slug, description="",
                            settings={"default_voting_days": 7})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _topic(db, org, name, **kw):
    t = models.Topic(name=name, org_id=org.id, **kw)
    db.add(t)
    db.flush()
    return t


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _setup(db, *, role="steward"):
    org = _org(db, "si-org")
    author = _user(db, "si-author")
    make_org_membership(db, org_id=org.id, user_id=author.id, role=role)
    _topic(db, org, "Zoning", purpose="Land use", category="Planning")
    _topic(db, org, "Parks", purpose="Green space")
    db.commit()
    return org, author


def _mock_llm(monkeypatch, payload_text, *, capture=None):
    def fake(*, system, user, api_key, model):
        if capture is not None:
            capture["system"] = system
            capture["user"] = user
            capture["model"] = model
        return payload_text
    monkeypatch.setattr(smart_import, "_call_anthropic", fake)


_GOOD_JSON = """[
  {"title": "Rezone 5th Street", "body": "Rezone the 5th Street parcel from R1 to mixed-use to allow a corner store.",
   "topics": [{"topic_name": "Zoning", "relevance": 1.0}], "reasoning": "Clearly a zoning matter."}
]"""


def test_text_input_well_formed(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "5th Street rezoning hearing..."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == 1
    assert body["summary"]["valid"] == 1
    item = body["items"][0]
    assert item["proposal"]["title"] == "Rezone 5th Street"
    assert item["proposal"]["voting_method"] == "binary"
    assert item["ai_reasoning"] == "Clearly a zoning matter."
    assert "source_text_preview" in body
    # no rows written
    assert test_db.query(models.Proposal).count() == 0


def test_pdf_input(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    # Build a tiny real PDF with reportlab if available; else mock extraction.
    pdf_bytes = _make_pdf("Agenda: 5th Street rezoning") if _have_reportlab() else None
    if pdf_bytes is None:
        monkeypatch.setattr(smart_import, "extract_pdf_text", lambda raw: "Agenda text")
        pdf_bytes = b"%PDF-1.4 fake"
    r = client.post(
        f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
        files={"file": ("agenda.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["total"] == 1


def test_unknown_topic_warns_and_drops(client, test_db, monkeypatch):
    # Phase 72c — an unknown topic is warn-and-drop, NOT an item error (the
    # change to _resolve_import_topics applies to smart-import too, since it
    # shares the per-item preview pipeline). The item stays valid and imports
    # topic-less with a warning naming the skipped topic.
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, """[
      {"title": "Item", "body": "Body text here.",
       "topics": [{"topic_name": "Nonexistent Topic", "relevance": 1.0}], "reasoning": "x"}
    ]""")
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "some agenda"})
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert not item["errors"].get("topics")
    assert item["proposal"] is not None
    assert item["proposal"]["topics"] == []
    assert any("Nonexistent Topic" in w for w in item["warnings"])


def test_meeting_date_maps_to_voting_end_date(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda", "meeting_date": "2026-06-23"})
    prop = r.json()["items"][0]["proposal"]
    assert prop["voting_end_date"] is not None


def test_no_meeting_date_null(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda"})
    assert r.json()["items"][0]["proposal"]["voting_end_date"] is None


def test_instructions_in_prompt(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    cap = {}
    _mock_llm(monkeypatch, _GOOD_JSON, capture=cap)
    client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                json={"content": "agenda", "instructions": "focus on zoning items"})
    assert "focus on zoning items" in cap["user"]
    # org topic taxonomy is grounded in the prompt
    assert "Zoning" in cap["user"]


def test_malformed_llm_response(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, "I'm sorry, I cannot do that.")
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json().get("warnings")


def test_llm_timeout(client, test_db, monkeypatch):
    org, author = _setup(test_db)

    def boom(**kw):
        raise TimeoutError("timed out")
    monkeypatch.setattr(smart_import, "_call_anthropic", boom)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json().get("warnings")


def test_no_api_key_503(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda"})
    assert r.status_code == 503


def test_empty_text_422(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "   "})
    assert r.status_code == 422


def test_text_too_large_422(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    big = "x" * (smart_import.MAX_TEXT_BYTES + 10)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": big})
    assert r.status_code == 422


def test_corrupt_pdf_422(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(
        f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
        files={"file": ("bad.pdf", b"not a real pdf", "application/pdf")},
    )
    assert r.status_code == 422


def test_member_without_create_403(client, test_db, monkeypatch):
    org = _org(test_db, "si-org2")
    # member role has no proposal.create
    plain = _user(test_db, "plain")
    make_org_membership(test_db, org_id=org.id, user_id=plain.id, role="member")
    test_db.commit()
    _mock_llm(monkeypatch, _GOOD_JSON)
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(plain),
                    json={"content": "agenda"})
    assert r.status_code == 403


def test_no_rows_written_on_validation_failure(client, test_db, monkeypatch):
    org, author = _setup(test_db)
    # LLM returns an item with a too-long title (>500) → per-item error, no write.
    _mock_llm(monkeypatch, '[{"title": "' + ("T" * 600) + '", "body": "b", "topics": [], "reasoning": "x"}]')
    r = client.post(f"/api/orgs/{org.slug}/proposals/smart-import", headers=_auth(author),
                    json={"content": "agenda"})
    assert r.status_code == 200
    assert test_db.query(models.Proposal).count() == 0


# --- pure-unit coverage of the parser ---

def test_parse_llm_array_handles_wrapped_json():
    assert smart_import.parse_llm_array('Here you go: [{"title":"a"}] done') == [{"title": "a"}]
    assert smart_import.parse_llm_array("no json here") is None
    assert smart_import.parse_llm_array("[]") == []


# --- helpers ---

def _have_reportlab() -> bool:
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def _make_pdf(text: str) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()
