import pytest

import models
from scripts.phase109_release_qa_bootstrap import bootstrap, SLUG, ACCOUNTS


def test_release_bootstrap_is_private_nonadmin_opted_out_and_collision_safe(db):
    result = bootstrap(db, "Synthetic-owner-password-109!", "Synthetic-member-password-109!")
    db.commit()
    org = db.get(models.Organization, result["org_id"])
    assert (org.slug, org.join_policy, org.discoverability, org.activity_visibility) == (SLUG, "invite", "hidden", "members_only")
    assert org.is_demo is False
    users = db.query(models.User).filter(models.User.username.in_([a[0] for a in ACCOUNTS])).all()
    assert len(users) == 2 and not any(user.is_admin for user in users)
    assert all(user.email.endswith("@demo.example") and user.email_verified for user in users)
    prefs = db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id.in_([u.id for u in users])).all()
    assert prefs and not any(pref.enabled for pref in prefs)
    assert db.query(models.Proposal).filter_by(org_id=org.id).count() == 0
    hashes = {user.id: user.password_hash for user in users}
    with pytest.raises(ValueError, match="already exists"):
        bootstrap(db, "Different-owner-password-109!", "Different-member-password-109!")
    assert {user.id: user.password_hash for user in users} == hashes
    assert db.query(models.OrgMembership).filter_by(org_id=org.id).count() == 2
    assert "password" not in str(result)


def test_bootstrap_refuses_account_collision_before_creating_org(db):
    db.add(models.User(username=ACCOUNTS[0][0], display_name="Existing", password_hash="untouched"))
    db.flush()
    with pytest.raises(ValueError, match="identity already exists"):
        bootstrap(db, "Synthetic-owner-password-109!", "Synthetic-member-password-109!")
    assert db.query(models.Organization).filter_by(slug=SLUG).count() == 0
