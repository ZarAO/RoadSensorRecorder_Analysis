"""
Unit tests for the GeoJSON writers and the folium map.

Three contracts are pinned here: coordinate order is [lon, lat], a missing
metric is serialized as null (a bare NaN token is rejected by strict parsers),
and a low-speed segment is drawn in magenta with its own legend entry.
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from road_quality_analyzer.artifacts import (
    LOW_SPEED_COLOR,
    LOW_SPEED_LEGEND_LABEL,
    create_segments_map_html,
    export_events_geojson,
    export_segments_geojson,
)

LAT0, LON0 = 50.4, 30.5


def _reject_constant(token):
    raise AssertionError(f'GeoJSON contains the non-standard JSON constant {token!r}')


def load_strict(path) -> dict:
    """Parse like QGIS / JSON.parse do: NaN and Infinity are hard errors."""
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=_reject_constant)


@pytest.fixture
def track():
    """100 samples of a 14 m/s drive heading north-east from (50.4, 30.5)."""
    t_grid = np.arange(0.0, 10.0, 0.1)
    s_grid = 14.0 * t_grid                       # 0 .. 140 m
    gps_time = np.arange(0.0, 10.5, 0.5)
    gps_lat = LAT0 + gps_time * 1e-4
    gps_lon = LON0 + gps_time * 2e-4
    return t_grid, s_grid, gps_time, gps_lat, gps_lon


@pytest.fixture
def segments_df():
    """One full segment plus a short one whose PSD metrics could not be computed."""
    return pd.DataFrame([
        {
            'seg_id': 0, 's_start': 0.0, 's_end': 100.0, 'length_m': 100.0,
            'partial': False, 'iri_multi': 2.5, 'iri_psd_raw': 1.2, 'iri_psd': 1.2,
            'grms': 0.05, 'mean_speed_kmh': 50.4, 'speed_valid': True,
            'dx_le_03_share': 1.0, 'anomaly_count': 2,
            'low_speed_class': 'normal', 'needs_class12_survey': False,
            'events_per_km': 20.0,
            'psd_sqrt_scalar': 0.03, 'psd_scalar_mode': 'mean_psd_sqrt',
            'psd_band_power': 0.001,
        },
        {
            'seg_id': 1, 's_start': 100.0, 's_end': 140.0, 'length_m': 40.0,
            'partial': True, 'iri_multi': np.nan, 'iri_psd_raw': np.nan,
            'iri_psd': np.nan, 'grms': 0.04, 'mean_speed_kmh': 50.4,
            'speed_valid': True, 'dx_le_03_share': 1.0,
            'anomaly_count': 0, 'low_speed_class': 'normal',
            'needs_class12_survey': False, 'events_per_km': 0.0,
            'psd_sqrt_scalar': np.nan,
            'psd_scalar_mode': 'mean_psd_sqrt', 'psd_band_power': np.nan,
        },
    ])


@pytest.fixture
def low_speed_segments_df(segments_df):
    """The same track, but the first segment could only be crawled at 9 km/h."""
    df = segments_df.copy()
    for column, value in (('iri_multi', np.nan), ('mean_speed_kmh', 9.0),
                          ('speed_valid', False), ('low_speed_class', 'invalid'),
                          ('needs_class12_survey', True), ('events_per_km', 40.0)):
        df.at[0, column] = value
    return df


def test_segments_geojson_short_segment_serializes_null(tmp_path, track, segments_df):
    """A segment shorter than fs*2 stores NaN metrics; the file must carry null."""
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'roughness.geojson'

    export_segments_geojson(segments_df, s_grid, gps_time, gps_lat, gps_lon,
                            t_grid, str(path))

    assert 'NaN' not in path.read_text(encoding='utf-8')

    props = load_strict(path)['features'][1]['properties']
    assert props['iri_psd_raw'] is None
    assert props['iri_psd'] is None
    assert props['iri_multi'] is None
    assert props['psd_band_power'] is None
    # A finite metric on the same feature must survive untouched
    assert props['grms'] == pytest.approx(0.04)


def test_segments_geojson_coordinate_order_is_lon_lat(tmp_path, track, segments_df):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'roughness.geojson'

    export_segments_geojson(segments_df, s_grid, gps_time, gps_lat, gps_lon,
                            t_grid, str(path))

    geometry = load_strict(path)['features'][0]['geometry']
    assert geometry['type'] == 'LineString'

    lon, lat = geometry['coordinates'][0]
    assert lon == pytest.approx(LON0, abs=0.01)
    assert lat == pytest.approx(LAT0, abs=0.01)
    # A (lat, lon) swap would put every vertex ~20 degrees away
    assert abs(lon - LAT0) > 10.0


def test_events_geojson_point_coordinate_order(tmp_path, track):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    anomaly_mask = np.zeros(len(t_grid), dtype=bool)
    anomaly_mask[[10, 42, 77]] = True
    path = tmp_path / 'events.geojson'

    export_events_geojson(s_grid, anomaly_mask, gps_time, gps_lat, gps_lon,
                          t_grid, str(path))

    features = load_strict(path)['features']
    assert len(features) == 3

    for feature in features:
        lon, lat = feature['geometry']['coordinates']
        assert lon == pytest.approx(LON0, abs=0.01)
        assert lat == pytest.approx(LAT0, abs=0.01)
        assert feature['properties']['event_type'] == 'threshold_10ms2'

    assert features[1]['properties']['distance_m'] == pytest.approx(s_grid[42])


def test_segments_geojson_carries_the_low_speed_properties(tmp_path, track,
                                                           low_speed_segments_df):
    """The Class 1/2 flag and the event rate must reach QGIS with the geometry."""
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'roughness.geojson'

    export_segments_geojson(low_speed_segments_df, s_grid, gps_time, gps_lat,
                            gps_lon, t_grid, str(path))

    crawled, driven = (f['properties'] for f in load_strict(path)['features'])

    assert crawled['low_speed_class'] == 'invalid'
    assert crawled['needs_class12_survey'] is True
    assert crawled['events_per_km'] == pytest.approx(40.0)
    # Labels only: the low-speed segment never carries a number for IRI_multi
    assert crawled['iri_multi'] is None

    assert driven['low_speed_class'] == 'normal'
    assert driven['needs_class12_survey'] is False
    assert driven['events_per_km'] == pytest.approx(0.0)


# --- Map ----------------------------------------------------------------------

def test_map_draws_low_speed_segments_in_magenta_with_a_legend(tmp_path, track,
                                                               low_speed_segments_df):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(low_speed_segments_df, s_grid, gps_time, gps_lat,
                             gps_lon, t_grid, str(path))

    html = path.read_text(encoding='utf-8')
    assert LOW_SPEED_COLOR == '#FF00FF'
    assert LOW_SPEED_COLOR in html
    assert LOW_SPEED_LEGEND_LABEL == 'Потребує обстеження профілометром (клас 1/2)'
    assert LOW_SPEED_LEGEND_LABEL in html


def test_map_tooltip_reports_class_speed_and_events(tmp_path, track,
                                                    low_speed_segments_df):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(low_speed_segments_df, s_grid, gps_time, gps_lat,
                             gps_lon, t_grid, str(path))

    html = path.read_text(encoding='utf-8')
    assert 'invalid' in html
    assert '9.0 км/год' in html
    assert '40.00' in html  # events_per_km


def polyline_options(html: str) -> list:
    """The Leaflet option dicts folium emits, one per drawn polyline."""
    return [
        json.loads(match.group(0))
        for match in re.finditer(r'\{"bubblingMouseEvents".*?"weight": [0-9.]+\}', html)
    ]


def test_map_draws_low_speed_segments_thicker_than_graded_ones(tmp_path, track,
                                                               low_speed_segments_df):
    """Colour alone is not the signal: the spec also asks for a heavier line."""
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(low_speed_segments_df, s_grid, gps_time, gps_lat,
                             gps_lon, t_grid, str(path))

    options = polyline_options(path.read_text(encoding='utf-8'))
    low_speed = [o['weight'] for o in options if o['color'] == LOW_SPEED_COLOR]
    graded = [o['weight'] for o in options
              if o['color'] not in (LOW_SPEED_COLOR, '#000000', 'gray')]
    outlines = sorted(o['weight'] for o in options if o['color'] == '#000000')

    assert len(low_speed) == 1 and len(graded) == 1
    assert min(low_speed) > max(graded)
    # The black outline under the magenta line grows with it, or the extra width
    # of the colour line would eat the outline instead of showing
    assert len(outlines) == 2 and outlines[-1] > outlines[0]


def test_low_speed_colour_is_off_the_iri_ramp(tmp_path, track, segments_df):
    """Magenta must not collide with any bucket of the green-blue-orange-red ramp."""
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    df = pd.concat([segments_df] * 2, ignore_index=True)
    df['seg_id'] = range(len(df))
    df['s_start'] = [0.0, 35.0, 70.0, 105.0]
    df['s_end'] = [35.0, 70.0, 105.0, 140.0]
    # Spread over the whole scale so every colour bucket is exercised
    df['iri_multi'] = [1.0, 2.0, 3.0, 4.0]
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(df, s_grid, gps_time, gps_lat, gps_lon, t_grid, str(path))

    html = path.read_text(encoding='utf-8')
    ramp = {o['color'] for o in polyline_options(html)} - {'#000000', 'gray'}
    assert len(ramp) == 4
    assert LOW_SPEED_COLOR not in ramp


def test_map_has_no_low_speed_legend_without_low_speed_segments(tmp_path, track,
                                                                segments_df):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(segments_df, s_grid, gps_time, gps_lat, gps_lon,
                             t_grid, str(path))

    html = path.read_text(encoding='utf-8')
    assert LOW_SPEED_LEGEND_LABEL not in html
    assert LOW_SPEED_COLOR not in html


def test_map_draws_segments_even_when_every_iri_multi_is_nan(tmp_path, track,
                                                             low_speed_segments_df):
    """
    A drive that never cleared 20 km/h has no IRI_multi at all; the colour scale
    cannot be built from it, and the segments must still be drawn - otherwise the
    worst road in the dataset would be an empty map.
    """
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    df = low_speed_segments_df.copy()
    df['iri_multi'] = np.nan
    df['needs_class12_survey'] = True
    df['low_speed_class'] = 'invalid'
    path = tmp_path / 'segments_map.html'

    create_segments_map_html(df, s_grid, gps_time, gps_lat, gps_lon, t_grid, str(path))

    html = path.read_text(encoding='utf-8')
    assert LOW_SPEED_COLOR in html
    assert LOW_SPEED_LEGEND_LABEL in html


def test_geojson_is_valid_featurecollection(tmp_path, track, segments_df):
    t_grid, s_grid, gps_time, gps_lat, gps_lon = track
    anomaly_mask = np.zeros(len(t_grid), dtype=bool)
    anomaly_mask[5] = True

    segments_path = tmp_path / 'roughness.geojson'
    events_path = tmp_path / 'events.geojson'
    export_segments_geojson(segments_df, s_grid, gps_time, gps_lat, gps_lon,
                            t_grid, str(segments_path))
    export_events_geojson(s_grid, anomaly_mask, gps_time, gps_lat, gps_lon,
                          t_grid, str(events_path))

    for path, geometry_types in ((segments_path, {'LineString', 'Point'}),
                                 (events_path, {'Point'})):
        document = load_strict(path)
        assert document['type'] == 'FeatureCollection'
        assert document['features']

        for feature in document['features']:
            assert feature['type'] == 'Feature'
            assert feature['geometry']['type'] in geometry_types
            assert feature['geometry']['coordinates']
            assert feature['properties']
