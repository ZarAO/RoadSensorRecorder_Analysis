"""
Unit tests for the statistics/calibration module on synthetic pairs with a
known ground truth (seeded rng — research determinism rule).
"""

import numpy as np
import pandas as pd
import pytest

from calibrate import (
    bland_altman, fit_eq3, fit_grms_speed, loro, validation_stats,
)

SEED = 20260820


def _pairs(n=120, A=6.0, B=0.4, noise=0.05, road='R1', rng=None):
    rng = rng or np.random.default_rng(SEED)
    sqrt_psd = rng.uniform(0.1, 1.0, n)
    return pd.DataFrame({
        'road': road,
        'psd_sqrt_scalar': sqrt_psd,
        'iri_ref': A * sqrt_psd + B + rng.normal(0, noise, n),
        'grms': sqrt_psd * 0.02,
        'mean_speed_kmh': rng.uniform(40, 70, n),
        'iri_multi': A * sqrt_psd + B - 1.0,   # constant -1 offset for Bland-Altman
    })


def test_fit_eq3_recovers_known_coefficients():
    fit = fit_eq3(_pairs())
    assert fit['A'] == pytest.approx(6.0, abs=0.1)
    assert fit['B'] == pytest.approx(0.4, abs=0.05)
    assert fit['r2'] > 0.98
    assert fit['n'] == 120
    assert fit['A_theil_sen'] == pytest.approx(6.0, abs=0.15)
    assert fit['mae'] < 0.1 and fit['rmse'] < 0.12


def test_validation_stats_monotone_data():
    pairs = _pairs(noise=0.0)
    stats = validation_stats(pairs, 'psd_sqrt_scalar')
    assert stats['spearman_rho'] == pytest.approx(1.0)
    assert stats['pearson_r'] == pytest.approx(1.0, abs=1e-6)
    assert stats['n'] == 120


def test_bland_altman_constant_offset():
    pairs = _pairs(noise=0.0)
    ba = bland_altman(pairs, 'iri_multi')
    assert ba['bias'] == pytest.approx(-1.0, abs=1e-9)
    assert ba['loa_low'] == pytest.approx(-1.0, abs=1e-6)
    assert ba['loa_high'] == pytest.approx(-1.0, abs=1e-6)


def test_loro_two_roads():
    rng = np.random.default_rng(SEED)
    pairs = pd.concat([
        _pairs(road='M-03', rng=rng),
        _pairs(road='T1016', rng=rng),
    ], ignore_index=True)
    result = loro(pairs)
    assert set(result.keys()) == {'M-03', 'T1016'}
    for held_out in result.values():
        assert held_out['r2'] > 0.95
        assert held_out['mae'] < 0.1
        assert 'A_train' in held_out and 'B_train' in held_out


def test_fit_grms_speed_shape():
    fit = fit_grms_speed(_pairs())
    assert set(fit) >= {'a_grms', 'b_speed', 'c_const', 'r2', 'mae', 'rmse', 'n'}
    # iri_ref is a pure function of grms (=sqrt_psd*0.02) up to noise -> high r2
    assert fit['r2'] > 0.95
