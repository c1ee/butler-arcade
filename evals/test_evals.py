"""One test per Eval family: its pass rate over every Run of its selected cases must meet the family's bar."""

import pytest

from evals.report import FAMILIES, score


@pytest.mark.parametrize("family", FAMILIES)
def test_family_meets_its_bar(results, family):
    s = score(results, family)
    if not s.total and family != "leak":  # a leak in any family still fails Leak
        pytest.skip(f"no {s.label} cases selected")
    assert s.ok, (f"{s.label}: {s.passed}/{s.total} Runs passed" +
                  (f", plus {s.elsewhere} Runs of other families leaked" if s.elsewhere else ""))
