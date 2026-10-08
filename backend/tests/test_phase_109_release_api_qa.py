import pytest

from scripts.phase109_release_api_qa import allowed_url, run, METHODS
from scripts.phase109_release_qa_bootstrap import bootstrap
from tests.test_ranked_choice_voting import test_db, client


def test_release_driver_real_local_api_with_isolated_bootstrap(client, test_db):
    owner = "Synthetic-owner-password-109!"
    member = "Synthetic-member-password-109!"
    bootstrap(test_db, owner, member)
    test_db.commit()
    saved = []
    result = run(client, owner, member, save_manifest=lambda data: saved.append(str(data)))
    assert result["completed"]
    assert set(result["open_proposals"]) == set(METHODS)
    assert set(result["closed_proposals"]) == set(METHODS)
    assert all(owner not in text and member not in text and "access_token" not in text for text in saved)


@pytest.mark.parametrize("url", ["https://evil.example", "http://www.liquiddemocracy.us", "https://www.liquiddemocracy.us/path",
                                "https://user:pass@www.liquiddemocracy.us", "http://localhost:8000/?redirect=evil"])
def test_driver_rejects_nonallowlisted_urls(url):
    with pytest.raises(ValueError):
        allowed_url(url)
