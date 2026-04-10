from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import engine as delegation_engine

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/seed", status_code=200)
def seed_demo(
    body: schemas.SeedRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    from seed_data import run_seed
    run_seed(db, scenario=body.scenario)
    return {"detail": f"Scenario '{body.scenario}' loaded successfully"}


@router.post("/time-simulation", status_code=200)
def simulate_time(
    body: schemas.TimeSimulationRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """
    Take a tally snapshot for a proposal at the given simulated time.
    Used by the demo time-forward control.
    """
    proposal = db.get(models.Proposal, body.proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    tally = delegation_engine.compute_tally(proposal, db)
    snapshot = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=body.simulated_time,
        yes_count=tally.yes,
        no_count=tally.no,
        abstain_count=tally.abstain,
        not_cast_count=tally.not_cast,
        total_eligible=tally.total_eligible,
    )
    db.add(snapshot)
    db.commit()
    return {"detail": "Snapshot recorded", "yes": tally.yes, "no": tally.no}


@router.get("/delegation-graph", response_model=schemas.DelegationGraph)
def system_delegation_graph(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """System-wide delegation graph for the admin panel."""
    from delegation_engine import graph_store

    all_delegations: list[models.Delegation] = db.query(models.Delegation).all()

    node_ids: set[str] = set()
    edges = []
    for d in all_delegations:
        node_ids.add(d.delegator_id)
        node_ids.add(d.delegate_id)
        topic_name = d.topic.name if d.topic else None
        edges.append(
            schemas.GraphEdge(
                source=d.delegator_id,
                target=d.delegate_id,
                topic_id=d.topic_id,
                topic_name=topic_name,
                chain_behavior=d.chain_behavior,
            )
        )

    nodes = []
    for uid in node_ids:
        user = db.get(models.User, uid)
        if user:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=user.display_name,
                    username=user.username,
                    weight=graph_store.compute_voting_weight(uid),
                )
            )

    return schemas.DelegationGraph(nodes=nodes, edges=edges)


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    return db.query(models.User).order_by(models.User.username).all()


@router.patch("/users/{user_id}/make-admin", response_model=schemas.UserOut)
def make_admin(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return user
