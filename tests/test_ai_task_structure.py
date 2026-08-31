"""The primary AI Task path requests native structured output."""

from hamie.connectors.ai_executor import ai_task_structure
from hamie.connectors.schemas import AI_RESPONSE_FIELDS


def test_ai_task_structure_covers_the_strict_response_schema() -> None:
    structure = ai_task_structure()
    assert set(structure) == set(AI_RESPONSE_FIELDS)
    assert structure["confidence"]["selector"]["select"]["options"] == [
        "low",
        "medium",
        "high",
    ]
    assert structure["probable_causes"]["selector"]["text"]["multiple"] is True
