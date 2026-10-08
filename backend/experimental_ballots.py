"""Strict shared input/stored-ballot decoding; omitted values stay omitted."""
from voting_methods import EXPERIMENTAL_VOTING_METHODS

MAX_BALLOT_OPTIONS = 120


def validate_ballot(method: str, payload: dict, option_ids=None) -> dict:
    """Validate a pure ballot, not the enclosing HTTP request.

    UUID syntax is enforced by the API schema. This pure helper also permits
    symbolic fixture IDs, but never coerces score types or incompatible fields.
    """
    if method not in EXPERIMENTAL_VOTING_METHODS:
        raise ValueError("Not an experimental voting method")
    if not isinstance(payload, dict):
        raise ValueError("Ballot must be an object")
    field = ("rank_groups" if method == "ranked_pairs" else
             "grades" if method == "majority_judgment" else "scores")
    if set(payload) - {field, "abstain"}:
        raise ValueError("Incompatible ballot fields")
    abstain = payload.get("abstain", False)
    if type(abstain) is not bool:
        raise ValueError("Abstain must be a boolean")
    if abstain:
        if field in payload:
            raise ValueError("Abstention cannot include preferences")
        return {"abstain": True}
    if field not in payload:
        raise ValueError("Missing ballot preferences")
    allowed = None if option_ids is None else set(option_ids)
    seen = set()

    def check_id(option_id):
        if not isinstance(option_id, str) or not option_id or len(option_id) > 200:
            raise ValueError("Invalid option ID")
        if allowed is not None and option_id not in allowed:
            raise ValueError("Option is no longer available on this proposal")
        if option_id in seen:
            raise ValueError("Repeated option ID")
        seen.add(option_id)
        if len(seen) > MAX_BALLOT_OPTIONS:
            raise ValueError("Too many ballot options")

    value = payload[field]
    if field == "rank_groups":
        if not isinstance(value, list) or len(value) > MAX_BALLOT_OPTIONS:
            raise ValueError("Rank groups must be a bounded list")
        result = []
        for group in value:
            if not isinstance(group, list) or not group or len(group) > MAX_BALLOT_OPTIONS:
                raise ValueError("Rank groups must be nonempty bounded lists")
            for option_id in group:
                check_id(option_id)
            result.append(sorted(group))
    else:
        if not isinstance(value, dict) or len(value) > MAX_BALLOT_OPTIONS:
            raise ValueError("Ratings must be a bounded object")
        result = {}
        for option_id, rating in value.items():
            check_id(option_id)
            if type(rating) is not int or not 0 <= rating <= 5:
                raise ValueError("Ratings must be integers from 0 to 5")
            result[option_id] = rating
    return {field: result}
