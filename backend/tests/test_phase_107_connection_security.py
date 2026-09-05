"""Phase 107 connection resource and authorization regressions."""
import asyncio
from contextlib import ExitStack
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from starlette.websockets import WebSocketDisconnect

import auth
import models
import websocket as live
from database import Base
from main import app
from tests.test_phase_38_authorization_audit import (
    _make_org, _make_user, _make_membership, _make_proposal,
    _make_sub_org_membership,
)


@pytest.fixture
def socket_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sockets.db'}", poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=0.2,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        org = _make_org(db, slug="socket-org")
        user = _make_user(db, "socket-user")
        _make_membership(db, org, user)
        proposal = _make_proposal(db, author=user, org_id=org.id)
        db.commit()
        ids = org.id, user.id, proposal.id
    app.dependency_overrides[live.get_websocket_session_factory] = lambda: factory
    startup = app.router.on_startup[:]
    app.router.on_startup.clear()
    yield engine, factory, ids
    app.router.on_startup[:] = startup
    app.dependency_overrides.pop(live.get_websocket_session_factory, None)
    assert not live.manager._connections
    engine.dispose()


TALLY = SimpleNamespace(not_cast=1, total_eligible=2, total_ballots_cast=1,
                        winners=["option"], tied=False)


def test_more_sockets_than_pool_capacity_and_healthy_payload(socket_db):
    engine, factory, (_, user_id, proposal_id) = socket_db
    with TestClient(app) as client, ExitStack() as stack:
        sockets = []
        for _ in range(4):
            ws = stack.enter_context(client.websocket_connect(f"/ws/proposals/{proposal_id}"))
            ws.send_json({"auth": auth.create_access_token(user_id)})
            # A portal callback waits for registration without timing sleeps.
            client.portal.call(wait_registered, proposal_id, len(sockets) + 1)
            sockets.append(ws)
            assert engine.pool.checkedout() == 0
        with factory() as db:
            assert db.execute(text("SELECT 1")).scalar() == 1
        client.portal.call(live.manager.broadcast_tally, proposal_id, TALLY)
        for ws in sockets:
            assert ws.receive_json() == dict(type="tally_update", proposal_id=proposal_id,
                not_cast=1, total_eligible=2, total_ballots_cast=1, winners=["option"], tied=False)
        assert engine.pool.checkedout() == 0


async def wait_registered(proposal_id, count):
    async def wait():
        while len(live.manager._connections.get(proposal_id, [])) != count:
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 3)


@pytest.mark.parametrize("change,code", [("membership",4403), ("inactive",4401),
                                         ("deleted",4404), ("private",4403)])
def test_committed_revocation_blocks_next_tally(socket_db, change, code):
    _, factory, (org_id, user_id, proposal_id) = socket_db
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            ws.send_json({"auth": auth.create_access_token(user_id)})
            client.portal.call(wait_registered, proposal_id, 1)
            with factory() as db:
                if change == "membership":
                    db.query(models.OrgMembership).filter_by(user_id=user_id).update({"status":"inactive"})
                elif change == "inactive":
                    db.get(models.User,user_id).is_active = False
                elif change == "deleted":
                    db.delete(db.get(models.Proposal,proposal_id))
                else:
                    sub = _make_org(db, slug="private", parent_org_id=org_id, settings_dict={"private": True})
                    db.get(models.Proposal,proposal_id).sub_org_id = sub.id
                db.commit()
            client.portal.call(live.manager.broadcast_tally, proposal_id, TALLY)
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == code


def test_idle_revocation(socket_db, monkeypatch):
    _, factory, (_, user_id, proposal_id) = socket_db
    monkeypatch.setattr(live, "IDLE_CHECK_SECONDS", 0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            ws.send_json({"auth": auth.create_access_token(user_id)})
            client.portal.call(wait_registered, proposal_id, 1)
            with factory() as db:
                db.get(models.User,user_id).is_active = False
                db.commit()
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401


@pytest.mark.parametrize("frame", ["binary", "list", "oversized", "missing", "expired"])
def test_bad_handshake(socket_db, frame):
    _, _, (_, user_id, proposal_id) = socket_db
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            if frame == "binary": ws.send_bytes(b"bad")
            elif frame == "list": ws.send_json([])
            elif frame == "oversized": ws.send_text("a" * 8193)
            elif frame == "expired": ws.send_json({"auth":auth.create_access_token(user_id,timedelta(seconds=-2))})
            else: ws.send_json({})
            with pytest.raises(WebSocketDisconnect) as exc: ws.receive_json()
            assert exc.value.code == 4401


def test_token_expires_while_idle(socket_db):
    _, _, (_, user_id, proposal_id) = socket_db
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            ws.send_json({"auth": auth.create_access_token(user_id, timedelta(seconds=2))})
            client.portal.call(wait_registered, proposal_id, 1)
            with pytest.raises(WebSocketDisconnect) as exc: ws.receive_json()
            assert exc.value.code == 4401


class FakeSocket:
    def __init__(self, fail=False): self.messages=[]; self.closed=[]; self.fail=fail
    async def send_text(self, payload):
        if self.fail: await asyncio.sleep(10)
        self.messages.append(payload)
    async def close(self, code): self.closed.append(code)


def test_slow_client_and_database_failure_fail_closed(monkeypatch):
    monkeypatch.setattr(live, "SEND_TIMEOUT", 0.02)
    async def scenario():
        manager=live.ConnectionManager()
        async def valid(): return 0, 9999999999
        async def broken(): raise RuntimeError("sensitive database error")
        slow, healthy, denied=FakeSocket(True),FakeSocket(),FakeSocket()
        for ws, check in [(slow,valid),(healthy,valid),(denied,broken)]: manager.register("p",ws,check)
        await asyncio.wait_for(manager.broadcast_tally("p",TALLY),0.5)
        assert len(healthy.messages)==1
        assert slow.messages==denied.messages==[]
        assert slow.closed==denied.closed==[1011]
        manager.disconnect("p", healthy)
        assert not manager._connections and not manager._validators and not manager._locks
    asyncio.run(scenario())


def test_filtered_canonical_viewers_match_full_set(socket_db):
    from eligibility import eligible_viewers_for_proposal
    _, factory, (org_id, user_id, proposal_id)=socket_db
    with factory() as db:
        parent=db.get(models.Organization,org_id)
        sub=_make_org(db,slug="sub",parent_org_id=org_id,settings_dict={"private":True})
        users=[db.get(models.User,user_id)]
        for role in ["admin","steward","member"]:
            u=_make_user(db,"viewer-"+role);_make_membership(db,parent,u,role);users.append(u)
        _make_sub_org_membership(db,sub,users[-1])
        proposal=db.get(models.Proposal,proposal_id);proposal.sub_org_id=sub.id;db.commit()
        for private in [True,False]:
            sub.settings={"private":private};db.commit()
            expected=eligible_viewers_for_proposal(db,proposal)
            for u in users:
                assert eligible_viewers_for_proposal(db,proposal,user_id=u.id)==({u.id}&expected)
        proposal.sub_org_id = None
        for context_org_id in [org_id, None]:
            proposal.org_id = context_org_id
            db.commit()
            expected = eligible_viewers_for_proposal(db, proposal)
            for u in users:
                assert eligible_viewers_for_proposal(db, proposal, user_id=u.id) == ({u.id} & expected)


def test_vote_and_retract_release_request_connection_before_broadcast(socket_db):
    from database import get_db
    engine, factory, (_, user_id, proposal_id) = socket_db
    def request_db():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = request_db
    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
                token=auth.create_access_token(user_id)
                ws.send_json({"auth":token})
                client.portal.call(wait_registered,proposal_id,1)
                headers={"Authorization":f"Bearer {token}"}
                response=client.post(f"/api/proposals/{proposal_id}/vote",headers=headers,json={"vote_value":"yes"})
                assert response.status_code==200,response.text
                assert response.json()["vote_value"]=="yes"
                message=ws.receive_json()
                assert message["yes"]==1 and message["no"]==0 and message["yes_pct"]==1.0
                response=client.delete(f"/api/proposals/{proposal_id}/vote",headers=headers)
                assert response.status_code==204,response.text
                assert ws.receive_json()["yes"]==0
                assert engine.pool.checkedout()==0
    finally:
        app.dependency_overrides.pop(get_db,None)


@pytest.mark.parametrize("mode", ["admin", "submember"])
def test_live_privileged_and_private_membership_revocation(socket_db,mode):
    _,factory,(org_id,user_id,proposal_id)=socket_db
    with factory() as db:
        user=db.get(models.User,user_id)
        if mode=="admin":
            user.is_admin=True
            db.query(models.OrgMembership).filter_by(user_id=user_id).delete()
        else:
            sub=_make_org(db,slug="private-live",parent_org_id=org_id,settings_dict={"private":True})
            db.get(models.Proposal,proposal_id).sub_org_id=sub.id
            _make_sub_org_membership(db,sub,user)
        db.commit()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            ws.send_json({"auth":auth.create_access_token(user_id)})
            client.portal.call(wait_registered,proposal_id,1)
            client.portal.call(live.manager.broadcast_tally,proposal_id,TALLY)
            assert ws.receive_json()["type"]=="tally_update"
            with factory() as db:
                if mode=="admin": db.get(models.User,user_id).is_active=False
                else: db.query(models.SubOrgMembership).filter_by(user_id=user_id).delete()
                db.commit()
            client.portal.call(live.manager.broadcast_tally,proposal_id,TALLY)
            with pytest.raises(WebSocketDisconnect) as exc: ws.receive_json()
            assert exc.value.code==(4401 if mode=="admin" else 4403)


@pytest.mark.parametrize("binary",[True,False])
def test_unsolicited_frame_closes_and_cleans_up(socket_db,binary):
    _,_,(_,user_id,proposal_id)=socket_db
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            ws.send_json({"auth":auth.create_access_token(user_id)})
            client.portal.call(wait_registered,proposal_id,1)
            if binary: ws.send_bytes(b"bad")
            else: ws.send_text("arbitrary data")
            with pytest.raises(WebSocketDisconnect) as exc: ws.receive_json()
            assert exc.value.code==4400


def test_database_exception_is_safe_and_closed(socket_db,monkeypatch):
    engine,factory,(_,user_id,proposal_id)=socket_db
    from sqlalchemy.orm import Session
    def broken(*args,**kwargs): raise RuntimeError("database password should not escape")
    monkeypatch.setattr(Session,"get",broken)
    assert live.check_access(factory,proposal_id,auth.create_access_token(user_id))==(1011,0)
    assert engine.pool.checkedout()==0


def test_cancellation_removes_registration(socket_db):
    _,factory,(_,user_id,proposal_id)=socket_db
    class Socket(FakeSocket):
        async def accept(self): pass
        async def receive_text(self): return '{"auth":"'+auth.create_access_token(user_id)+'"}'
        async def receive(self): await asyncio.Future()
    async def scenario():
        manager=live.ConnectionManager(); ws=Socket()
        task=asyncio.create_task(live.serve_proposal_socket(ws,proposal_id,factory,manager))
        async def registered():
            while not manager._connections: await asyncio.sleep(.001)
        await asyncio.wait_for(registered(),3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not manager._connections and not manager._validators and not manager._locks
    asyncio.run(scenario())

@pytest.mark.parametrize("mode", ["timeout", "malformed"])
def test_handshake_timeout_and_malformed_json(socket_db,monkeypatch,mode):
    _,_,(_,_,proposal_id)=socket_db
    monkeypatch.setattr(live,"HANDSHAKE_TIMEOUT",0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/proposals/{proposal_id}") as ws:
            if mode=="malformed": ws.send_text("{bad-json")
            with pytest.raises(WebSocketDisconnect) as exc: ws.receive_json()
            assert exc.value.code==4401


def test_expiry_during_validation_prevents_send():
    async def scenario():
        manager=live.ConnectionManager();ws=FakeSocket()
        async def expires_during_query(): return 0, live.time.time()-1
        manager.register("p",ws,expires_during_query)
        await manager.broadcast_tally("p",TALLY)
        assert not ws.messages and ws.closed==[4401]
        assert not manager._connections
    asyncio.run(scenario())
