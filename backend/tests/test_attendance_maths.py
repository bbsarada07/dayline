import pytest

from app.services.attendance_service import standing


def test_below_threshold_spec_example():
    s = standing(40, 28, 75)
    assert s.status == "below"
    assert s.percentage == 70.0
    assert s.must_attend == 8
    assert s.statement == "Attend the next 8 classes to reach 75%"


def test_above_threshold_spec_example():
    s = standing(40, 36, 75)
    assert s.status == "ok"
    assert s.percentage == 90.0
    assert s.can_miss == 8
    assert s.statement == "You can miss 8 more classes and stay at 75%"


def test_no_classes_held():
    s = standing(0, 0, 75)
    assert s.status == "no_classes"
    assert s.percentage is None
    assert s.can_miss == 0
    assert s.must_attend == 0
    assert s.statement == "No classes held yet."


def test_exactly_at_threshold_counts_as_ok():
    s = standing(40, 30, 75)
    assert s.status == "ok"
    assert s.can_miss == 0
    assert s.statement == "You can miss 0 more classes and stay at 75%"


def test_singular_wording():
    assert standing(4, 3, 60).statement == "You can miss 1 more class and stay at 60%"
    assert standing(4, 2, 60).statement == "Attend the next class to reach 60%"


def test_percentage_rounds_down_never_up():
    # 74.96% must not be displayed as 75.0% when it is below the threshold.
    s = standing(2001, 1500, 75)
    assert s.status == "below"
    assert s.percentage == 74.9
    assert standing(3, 2, 75).percentage == 66.6


def test_threshold_comes_from_argument():
    assert standing(40, 30, 80).must_attend == 10  # (32 - 30) / 0.2
    assert standing(40, 36, 80).can_miss == 5  # 36 / 0.8 - 40


def test_threshold_of_100_when_below():
    s = standing(10, 9, 100)
    assert s.status == "below"
    assert s.must_attend is None


@pytest.mark.parametrize("threshold", [50, 60, 75, 80, 90])
def test_formulas_are_exact_bounds(threshold):
    """M is the most you can miss and stay at threshold; N is the fewest you must attend."""
    for held in range(1, 60):
        for attended in range(0, held + 1):
            s = standing(held, attended, threshold)
            if s.status == "ok":
                m = s.can_miss
                assert attended * 100 >= threshold * (held + m)
                assert attended * 100 < threshold * (held + m + 1)
            else:
                n = s.must_attend
                assert (attended + n) * 100 >= threshold * (held + n)
                assert (attended + n - 1) * 100 < threshold * (held + n - 1)


def test_invalid_input_rejected():
    with pytest.raises(ValueError):
        standing(10, 11, 75)
    with pytest.raises(ValueError):
        standing(10, 5, 0)
