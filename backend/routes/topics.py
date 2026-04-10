from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db

router = APIRouter(prefix="/api/topics", tags=["topics"])


@router.get("", response_model=list[schemas.TopicOut])
def list_topics(db: Session = Depends(get_db)):
    return db.query(models.Topic).order_by(models.Topic.name).all()


@router.post("", response_model=schemas.TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(
    body: schemas.TopicCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    if db.query(models.Topic).filter(models.Topic.name == body.name).first():
        raise HTTPException(status_code=400, detail="Topic name already exists")
    topic = models.Topic(**body.model_dump())
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic
