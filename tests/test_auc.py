import pytest

from remake_sensitivity.auc import trapezoidal_auc


def test_uneven_grid_auc_uses_weighted_trapezoids():
    assert trapezoidal_auc([(0.0, 0.0), (0.25, 1.0), (1.0, 1.0)]) == pytest.approx(
        0.875
    )
