from types import SimpleNamespace

import pytest

from app.services.attempts import min_question_seconds


@pytest.mark.parametrize("raw, want", [
    (None, 0), (0, 0), (5, 5), (60, 60), (61, 60), (1000, 60), (-3, 0), (2.5, 2), ("abc", 0), ("5", 0), (True, 0), (False, 0),
    (float("inf"), 0), (float("nan"), 0), ([5], 0), ({"a": 1}, 0),
])
def test_minimum_reading_time_is_a_safe_number_of_seconds(raw, want):
    settings = {} if raw is None else {"min_question_seconds": raw}
    assert min_question_seconds(SimpleNamespace(settings=settings)) == want


def test_an_exam_with_no_settings_has_no_wait():
    assert min_question_seconds(SimpleNamespace(settings=None)) == 0
