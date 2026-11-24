"""
Unit tests for the calibration model (spec 2026-11-15-calibration-model-and-
ablation-design.md) on synthetic pairs with a known ground truth (seeded rng).
"""

import numpy as np
import pandas as pd
import pytest

from profilometer_validation import calibration_model as cm

SEED = 20261115
GAMMA, DELTA, BETA, V0 = 1.8, 0.3, 0.02, cm.V0_KMH


def _section(name, n_bins=40, speeds=(60.0,), ref_lo=1.0, ref_hi=9.0, noise=0.0, seed=SEED,
             g0=0.0):
    """Pairs of one section: reference rises along the chainage; every pass
    sees R = (ref - delta)/gamma + beta (v - v0), i.e. the model holds exactly.
    With g0 > 0 the Grms carries a noise floor in quadrature."""
    rng = np.random.default_rng(seed)
    rows = []
    for run, speed in enumerate(speeds):
        for b in range(n_bins):
            ref = ref_lo + (ref_hi - ref_lo) * b / (n_bins - 1)
            r_true = (ref - DELTA) / GAMMA + BETA * (speed - V0)
            # back out a Grms consistent with Eq.6 nominal: R = 50.32 Grms - 0.06 v + 3.31
            grms_road = (r_true + 0.06 * speed - 3.31) / cm.EQ6_GRMS_COEF
            grms = np.sqrt(grms_road ** 2 + g0 ** 2) if g0 else grms_road
            raw = cm.EQ6_GRMS_COEF * grms - 0.06 * speed + 3.31 + rng.normal(0, noise)
            rows.append({'section': name, 'road': name, 'run_id': f'{name}-{run}',
                         'chainage_m': b * 100.0 + 50.0, 'iri_ref': ref, 'grms': grms,
                         'mean_speed_kmh': speed, 'iri_multi_raw': raw,
                         'iri_multi': max(0.0, raw), 'vehicle': 'van'})
    return pd.DataFrame(rows)


def test_eq6_grms_coefficient_matches_the_analyzer_table():
    from road_quality_analyzer.metrics.iri import IRI_MULTI_COEFFICIENTS, VehicleType
    assert cm.EQ6_GRMS_COEF == IRI_MULTI_COEFFICIENTS[VehicleType.GENERIC]['grms']


def test_beta_is_identified_only_by_passes_of_the_same_section():
    passes = pd.concat([_section('A', speeds=(30.0, 45.0, 60.0)),
                        _section('B', speeds=(40.0, 55.0, 70.0), ref_lo=1.0, ref_hi=3.0)])
    beta = cm.estimate_beta(passes)
    assert beta['slope_iri_per_kmh'] == pytest.approx(BETA, abs=1e-9)
    assert beta['n_bins'] == 80                     # sections never share a bin
    assert cm.estimate_beta(_section('A')) is None   # single pass: not identified


def test_fit_recovers_gamma_delta_with_known_beta_and_predicts_exactly():
    data = pd.concat([_section('A', speeds=(30.0, 60.0)), _section('B', speeds=(70.0,))])
    params = cm.fit(data, beta=BETA)
    assert params.gamma == pytest.approx(GAMMA, abs=1e-9)
    assert params.delta == pytest.approx(DELTA, abs=1e-9)
    np.testing.assert_allclose(cm.predict(data, params), data['iri_ref'], atol=1e-9)


def test_ignoring_beta_biases_the_fit_across_speeds():
    data = pd.concat([_section('A', speeds=(30.0,)), _section('B', speeds=(70.0,))])
    good = cm.evaluate(cm.predict(data, cm.fit(data, beta=BETA)), data['iri_ref'])
    naive = cm.evaluate(cm.predict(data, cm.fit(data, beta=0.0)), data['iri_ref'])
    assert good['mae'] < 1e-9 < naive['mae']


def test_m2_finds_the_noise_floor_and_beats_m1_when_one_exists():
    data = _section('A', ref_lo=0.5, ref_hi=6.0, g0=0.01)
    m2 = cm.fit_m2(data, beta=BETA)
    assert m2.model == 'M2' and m2.g0 == pytest.approx(0.01, abs=0.0026)
    sse = lambda p: float(np.sum((cm.predict(data, p, clip=False) - data['iri_ref']) ** 2))
    assert sse(m2) < sse(cm.fit(data, beta=BETA))


def test_bias_only_is_the_published_constant_on_the_clipped_value():
    data = _section('A')
    k = cm.fit_bias_only(data)
    assert k == pytest.approx(float((data['iri_ref'] - data['iri_multi']).mean()))
    _, pred = cm.fit_and_predict(data, data, 'bias_only')
    np.testing.assert_allclose(pred, data['iri_multi'] + k)


def test_evaluate_rough_ratio_and_constant_prediction():
    out = cm.evaluate(np.array([1.0, 6.0, 9.0]), np.array([1.0, 8.0, 12.0]))
    assert out['rough_n'] == 2 and out['rough_pred_to_ref'] == pytest.approx(0.75)
    assert np.isnan(cm.evaluate(np.ones(3), np.array([1.0, 2.0, 3.0]))['spearman_rho'])


def test_holdout_models_and_leave_one_group_out():
    data = pd.concat([_section('A', speeds=(50.0,)), _section('B', speeds=(50.0,), ref_lo=2.0)])
    out = cm.leave_one_group_out(data, 'section')
    assert set(out) == {'A', 'B'} and set(out['A']) == set(cm.MODELS)
    assert out['A']['M1']['mae'] < 1e-6          # beta irrelevant at v = v0: exact transfer
    assert out['A']['book']['params'] == {}


def test_block_cv_keeps_blocks_whole_and_bootstrap_covers_truth():
    data = _section('A', n_bins=60, noise=0.05)
    data['iri_ref'] = data['iri_ref'] + np.random.default_rng(SEED).normal(0, 0.1, len(data))
    cv = cm.block_cv(data, n_folds=5, beta=BETA)
    assert cv['M1']['n'] == len(data) and cv['M1']['mae'] < cv['book']['mae']
    boot = cm.bootstrap_params(data, n_boot=200, beta=BETA)
    assert boot['gamma'] == pytest.approx(GAMMA, abs=0.05)
    assert boot['gamma_ci'][0] < boot['gamma'] < boot['gamma_ci'][1]
    assert boot['delta_ci'][0] < boot['delta'] < boot['delta_ci'][1]
    assert boot['n_blocks'] == 30 and boot['n_boot_ok'] == 200
    # same seed -> same interval (determinism rule)
    assert cm.bootstrap_params(data, n_boot=200, beta=BETA)['gamma_ci'] == boot['gamma_ci']


def test_beta_carries_a_t_interval_with_the_fixed_effects_dof():
    from scipy import stats as sps
    passes = _section('A', n_bins=30, speeds=(30.0, 40.0, 50.0, 60.0), noise=0.2)
    beta = cm.estimate_beta(passes)
    assert beta['dof'] == beta['n_rows'] - beta['n_bins'] - 1 == 120 - 30 - 1
    half = sps.t.ppf(0.975, beta['dof']) * beta['stderr']
    assert beta['ci_low'] == pytest.approx(beta['slope_iri_per_kmh'] - half)
    assert beta['ci_high'] == pytest.approx(beta['slope_iri_per_kmh'] + half)
    # one seeded draw: a 95 % interval may miss the truth; the estimate itself must not stray
    assert abs(beta['slope_iri_per_kmh'] - BETA) < 4 * beta['stderr'] and beta['confidence'] == 0.95


def test_leave_one_run_out_re_estimates_beta_and_removes_the_speed_bias():
    data = _section('A', speeds=(30.0, 40.0, 50.0, 60.0))
    out = cm.leave_one_run_out(data)
    assert set(out) == {'A-0', 'A-1', 'A-2', 'A-3'}
    for run, res in out.items():
        assert res['beta_identified'] and res['beta_train'] == pytest.approx(BETA, abs=1e-9)
        assert res['M1']['mae'] < 1e-9                    # exact model: any unseen speed
    # a constant offset cannot follow the speed: biased at both ends of the range
    assert out['A-0']['bias_only']['bias'] < 0 < out['A-3']['bias_only']['bias']


def test_leave_one_section_out_transfers_the_model_to_an_unseen_section():
    data = pd.concat([_section('A', speeds=(30.0, 50.0, 70.0)),
                      _section('B', n_bins=10, speeds=(40.0, 60.0), ref_lo=6.0, ref_hi=9.0)],
                     ignore_index=True)
    out = cm.leave_one_section_out(data, section_col='road')
    assert set(out) == {'A', 'B'}
    for res in out.values():                          # each training section identifies beta
        assert res['beta_identified'] and res['beta_train'] == pytest.approx(BETA, abs=1e-9)
        assert res['M1']['mae'] < 1e-9
    assert out['A']['M1']['n'] == 120 and out['B']['M1']['n'] == 20


def test_leave_one_section_out_without_beta_in_the_training_section():
    data = pd.concat([_section('A', speeds=(30.0, 50.0, 70.0)),
                      _section('B', n_bins=10, speeds=(60.0,), ref_lo=6.0, ref_hi=9.0)],
                     ignore_index=True)
    out = cm.leave_one_section_out(data, section_col='road')
    assert not out['A']['beta_identified'] and out['A']['beta_train'] == 0.0   # trained on B alone
    assert out['B']['beta_identified']


def test_leave_one_run_out_falls_back_to_beta_zero_when_not_identified():
    data = _section('A', speeds=(30.0, 60.0))
    out = cm.leave_one_run_out(data)
    assert all(not r['beta_identified'] and r['beta_train'] == 0.0 for r in out.values())
