"""
Unit tests for the vehicle passport -> Eq.4/5/6 parameter resolver.

The mapping tables are documented assumptions of the method (dissertation
section 2), so they are pinned literally here, the same way the book
coefficients are pinned in test_iri.py: a silent retune must fail a test.
"""

import numpy as np
import pytest

from road_quality_analyzer.metrics.iri import (
    IRI_MULTI_DEFAULT_PARAMS,
    VehicleType,
    compute_iri_multi,
)
from road_quality_analyzer.metrics.vehicle_params import (
    DAMPF_BY_SUSPENSION_CONDITION,
    EQUATION_BY_VEHICLE_TYPE,
    NPEOP_BY_LOAD,
    STIF_BY_SUSPENSION_TYPE,
    ResolvedVehicleParams,
    resolve_vehicle_params,
    tyre_size_factor,
)
from road_quality_analyzer.segmentation.segment_100m import (
    aggregate_segment_metrics,
    create_segments_dataframe,
)

FS = 100.0

# The validation carrier of 2026-08-20 exactly as the recorder wrote it (contract v3.1)
FORD_TRANSIT = {
    'vehicle_id': '95de9ea6-9c9f-4369-8b8f-bf542fa53f8d',
    'vehicle_type': 'van',
    'vehicle_make_model': 'Ford Transit',
    'vehicle_year': '2011',
    'vehicle_suspension_type': 'torsion_beam',
    'vehicle_suspension_condition': 'worn',
    'vehicle_tire_size': '215/75R16',
    'vehicle_tire_type': 'summer',
    'vehicle_load': 'half_load',
    'vehicle_mount': 'console',
    'vehicle_mount_rigid': 'true',
}


# --- Mapping tables (documented assumptions, pinned) ---------------------------

def test_mapping_tables_are_pinned_literally():
    assert EQUATION_BY_VEHICLE_TYPE == {'van': VehicleType.LEV, 'sedan': VehicleType.DSD}
    assert NPEOP_BY_LOAD == {
        'driver_only': 1.0, 'two_people': 2.0, 'half_load': 3.0, 'full_load': 4.0,
    }
    assert STIF_BY_SUSPENSION_TYPE == {
        'leaf_spring': 1.2, 'independent': 1.0, 'torsion_beam': 1.0, 'air': 0.8,
    }
    assert DAMPF_BY_SUSPENSION_CONDITION == {'new': 1.0, 'good': 1.0, 'worn': 0.8}


@pytest.mark.parametrize('size, expected', [
    ('215/75R16', 1.0),
    ('235/65R17', 1.0),
    ('195/65R15', 0.9),
    ('175/70R14', 0.7),
    ('165/70R13', 0.7),
    ('215/75 R16', 1.0),   # spacing tolerated
    ('215/75r16', 1.0),    # case tolerated
])
def test_tyre_size_factor_follows_rim_diameter_rule(size, expected):
    assert tyre_size_factor(size) == expected


def test_tyre_size_factor_is_none_for_unparsable_size():
    assert tyre_size_factor('unknown') is None
    assert tyre_size_factor('') is None


# --- Resolver ----------------------------------------------------------------

def test_ford_transit_passport_resolves_to_eq4_with_documented_parameters():
    resolved = resolve_vehicle_params(FORD_TRANSIT)

    assert isinstance(resolved, ResolvedVehicleParams)
    assert resolved.vehicle_type is VehicleType.LEV
    assert resolved.equation == 'eq4'
    assert resolved.params == {'npeop': 3.0, 'stif': 1.0, 'dampf': 0.8, 'tyres': 1.0}
    assert resolved.mount_rigid is True
    assert resolved.warnings == []


def test_empty_passport_falls_back_to_generic_book_defaults():
    """A pre-v3 recording has no passport: the result must equal today's pipeline."""
    resolved = resolve_vehicle_params({})

    assert resolved.vehicle_type is VehicleType.GENERIC
    assert resolved.equation == 'eq6'
    assert resolved.params == IRI_MULTI_DEFAULT_PARAMS
    assert set(resolved.provenance.values()) == {'default'}
    assert resolved.mount_rigid is None
    assert resolved.warnings == []


@pytest.mark.parametrize('body, expected_type, expected_eq', [
    ('sedan', VehicleType.DSD, 'eq5'),
    ('hatchback', VehicleType.GENERIC, 'eq6'),
    ('crossover', VehicleType.GENERIC, 'eq6'),
    ('suv', VehicleType.GENERIC, 'eq6'),
    ('truck', VehicleType.GENERIC, 'eq6'),
])
def test_body_type_selects_equation_set(body, expected_type, expected_eq):
    resolved = resolve_vehicle_params({'vehicle_type': body})

    assert resolved.vehicle_type is expected_type
    assert resolved.equation == expected_eq


def test_provenance_separates_book_assumption_and_default():
    resolved = resolve_vehicle_params(FORD_TRANSIT)
    assert resolved.provenance == {
        'equation': 'book',        # van is a guidebook vehicle class
        'npeop': 'assumption',     # cargo mass as passenger equivalents
        'stif': 'assumption',
        'dampf': 'assumption',
        'tyres': 'assumption',
    }

    two_people = resolve_vehicle_params({'vehicle_type': 'sedan', 'vehicle_load': 'two_people'})
    assert two_people.provenance['npeop'] == 'book'   # a passenger count is the book's own variable
    assert two_people.provenance['stif'] == 'default'

    generic = resolve_vehicle_params({'vehicle_type': 'suv'})
    assert generic.provenance['equation'] == 'default'   # no SUV class in the guidebook


def test_unknown_token_keeps_default_and_records_warning():
    resolved = resolve_vehicle_params({'vehicle_load': 'trailer', 'vehicle_tire_size': 'big'})

    assert resolved.params['npeop'] == IRI_MULTI_DEFAULT_PARAMS['npeop']
    assert resolved.params['tyres'] == IRI_MULTI_DEFAULT_PARAMS['tyres']
    assert resolved.provenance['npeop'] == 'default'
    assert resolved.provenance['tyres'] == 'default'
    assert any('vehicle_load' in w for w in resolved.warnings)
    assert any('vehicle_tire_size' in w for w in resolved.warnings)


def test_mount_rigid_false_is_reported_as_low_confidence():
    resolved = resolve_vehicle_params({'vehicle_mount_rigid': 'false'})

    assert resolved.mount_rigid is False
    assert any('mount' in w.lower() for w in resolved.warnings)


def test_resolver_is_deterministic():
    assert resolve_vehicle_params(FORD_TRANSIT) == resolve_vehicle_params(dict(FORD_TRANSIT))


# --- Segment metrics: additive column, iri_multi untouched --------------------

def constant_speed_segment(n: int = 700, speed_mps: float = 15.0, amplitude_g: float = 0.05):
    t = np.arange(n) / FS
    s_grid = speed_mps * t
    v_grid = np.full(n, speed_mps)
    a = amplitude_g * np.sin(2 * np.pi * 3.0 * t)
    return np.arange(n), a, v_grid, s_grid


def test_generic_defaults_make_vehicle_column_equal_to_iri_multi():
    indices, a, v_grid, s_grid = constant_speed_segment()

    metrics = aggregate_segment_metrics(
        seg_id=0, indices=indices, a_vertical_g=a, a_vertical_g_psd=a,
        v_grid=v_grid, s_grid=s_grid, fs=FS,
        vehicle_params=resolve_vehicle_params({}),
    )

    assert metrics['iri_multi_vehicle'] == metrics['iri_multi']
    assert metrics['iri_multi_equation'] == 'eq6'


def test_missing_vehicle_params_argument_keeps_todays_behaviour_and_adds_generic_column():
    indices, a, v_grid, s_grid = constant_speed_segment()

    metrics = aggregate_segment_metrics(
        seg_id=0, indices=indices, a_vertical_g=a, a_vertical_g_psd=a,
        v_grid=v_grid, s_grid=s_grid, fs=FS,
    )

    assert metrics['iri_multi_vehicle'] == metrics['iri_multi']
    assert metrics['iri_multi_equation'] == 'eq6'


def test_resolved_passport_changes_only_the_vehicle_column():
    indices, a, v_grid, s_grid = constant_speed_segment()
    resolved = resolve_vehicle_params(FORD_TRANSIT)

    df = create_segments_dataframe(
        s_grid, a, a, v_grid, FS, vehicle_params=resolved,
    )
    row = df.iloc[0]

    expected_generic = compute_iri_multi(
        row['grms'], row['mean_speed_kmh'],
        vehicle_type=VehicleType.GENERIC, **IRI_MULTI_DEFAULT_PARAMS)
    expected_vehicle = compute_iri_multi(
        row['grms'], row['mean_speed_kmh'],
        vehicle_type=VehicleType.LEV, npeop=3.0, stif=1.0, dampf=0.8, tyres=1.0)

    assert row['iri_multi'] == pytest.approx(expected_generic)
    assert row['iri_multi_vehicle'] == pytest.approx(expected_vehicle)
    assert row['iri_multi_vehicle'] != pytest.approx(row['iri_multi'])
    assert row['iri_multi_equation'] == 'eq4'


def test_vehicle_column_is_nan_outside_the_survey_speed_range_like_iri_multi():
    indices, a, v_grid, s_grid = constant_speed_segment(speed_mps=3.0)   # 10.8 km/h

    metrics = aggregate_segment_metrics(
        seg_id=0, indices=indices, a_vertical_g=a, a_vertical_g_psd=a,
        v_grid=v_grid, s_grid=s_grid, fs=FS,
        vehicle_params=resolve_vehicle_params(FORD_TRANSIT),
    )

    assert np.isnan(metrics['iri_multi'])
    assert np.isnan(metrics['iri_multi_vehicle'])
