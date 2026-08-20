"""
End-to-end tests for the analyze() pipeline.

Every case runs on a small synthetic CSV built in tmp_path; the 11 MB shipped
recording is deliberately not used, so the suite stays fast and hermetic.
"""

import contextlib
import io

import numpy as np
import pandas as pd
import pytest

import road_quality_analyzer.segmentation as segmentation
from road_quality_analyzer.cli import analyze
from road_quality_analyzer.metrics.iri import compute_iri_psd
from road_quality_analyzer.segmentation.segment_100m import create_segments
from tests.conftest import G0, write_drive_csv

# Baseline drive: 40 s at 15 m/s = 600 m -> four full 100 m segments
BASELINE_SPEED_MPS = 15.0
BASELINE_SPEED_KMH = BASELINE_SPEED_MPS * 3.6
FS = 100.0
BAND_LOW_HZ, BAND_HIGH_HZ = 0.5, 6.0


def _baseline_excitation(t):
    """Deterministic in-band road excitation (m/s^2), no RNG involved."""
    return 0.4 * np.sin(2 * np.pi * 2.3 * t) + 0.15 * np.sin(2 * np.pi * 4.7 * t)


def run_analyze(input_path: str, output_dir) -> str:
    """
    Call analyze() with stdout captured in memory.

    The progress log is Cyrillic; both entry points reconfigure stdout to UTF-8,
    so a test must supply a Unicode-capable stream instead of the cp1252 console.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        analyze(input_path, str(output_dir))
    return buffer.getvalue()


@pytest.fixture
def pipeline_signals(monkeypatch):
    """
    Capture the arrays analyze() hands to segmentation.

    analyze() imports create_segments_dataframe at call time, so replacing the
    attribute on the segmentation package intercepts the real call; the spy
    delegates, so the run still produces its artifacts. The first call wins -
    analyze() repeats it once per PSD scalar mode with the same signals.
    """
    captured = {}
    original = segmentation.create_segments_dataframe

    def spy(s_grid, a_vertical_g, a_vertical_g_psd, *args, **kwargs):
        captured.setdefault('s_grid', s_grid)
        captured.setdefault('a_vertical_g', a_vertical_g)
        captured.setdefault('a_vertical_g_psd', a_vertical_g_psd)
        return original(s_grid, a_vertical_g, a_vertical_g_psd, *args, **kwargs)

    monkeypatch.setattr(segmentation, 'create_segments_dataframe', spy)
    return captured


@pytest.fixture(scope='module')
def baseline_run(tmp_path_factory):
    """One full analyze() pass, shared by the artifact and report assertions."""
    base = tmp_path_factory.mktemp('baseline')
    csv_path = write_drive_csv(
        base / 'drive.csv',
        duration_s=40.0,
        speed_mps=BASELINE_SPEED_MPS,
        a_vert=_baseline_excitation,
    )
    out_dir = base / 'out'
    log = run_analyze(csv_path, out_dir)
    return {
        'csv': csv_path,
        'out': out_dir,
        'log': log,
        'segments': pd.read_csv(out_dir / 'road_segments.csv'),
        'report': (out_dir / 'report.md').read_text(encoding='utf-8'),
    }


# --- Integrity: no GPS must fail loud, never fabricate distance ---------------

def test_analyze_missing_gps_fails_loud(drive_csv, tmp_path):
    """No Location rows -> ValueError, never a linear s = 0.1*i counter."""
    csv_path = drive_csv(duration_s=20.0, gps=False)

    with pytest.raises(ValueError, match='No Location rows'):
        run_analyze(csv_path, tmp_path / 'out')


def test_analyze_missing_gps_does_not_fabricate_distance(drive_csv, tmp_path):
    """The failed run must leave no artifact carrying an invented distance axis."""
    csv_path = drive_csv(duration_s=20.0, gps=False)
    out_dir = tmp_path / 'out'

    with pytest.raises(ValueError):
        run_analyze(csv_path, out_dir)

    assert not out_dir.exists(), 'analyze() wrote artifacts for a GPS-less recording'


# --- Artifacts ----------------------------------------------------------------

def test_analyze_writes_all_documented_artifacts(baseline_run):
    out = baseline_run['out']

    for name in ('road_segments.csv', 'roughness.geojson', 'events.geojson',
                 'segments_map.html', 'report.md'):
        assert (out / name).is_file(), f'missing artifact {name}'

    for stem in ('speed_vs_distance', 'accel_vs_distance',
                 'metrics_vs_distance', 'iri_psd_vs_distance'):
        assert (out / 'plots' / f'{stem}.png').is_file()
        assert (out / 'plots' / f'{stem}.pdf').is_file()


def test_segments_match_the_synthetic_drive(baseline_run):
    """600 m at a constant 54 km/h -> four full segments, all dx-compliant."""
    df = baseline_run['segments']

    assert (~df['partial']).sum() == 4
    assert df['mean_speed_kmh'].to_numpy() == pytest.approx(BASELINE_SPEED_KMH, rel=0.02)
    assert df['speed_valid'].all()
    # dx = v/fs = 0.15 m for every sample
    assert df['dx_le_03_share'].to_numpy() == pytest.approx(1.0)


# --- Edge trim ----------------------------------------------------------------

def test_pipeline_trims_filter_edges(drive_csv, tmp_path, pipeline_signals):
    """
    The analysis window must carry no filtfilt start-up transient.

    The excitation is a stationary 2 Hz cosine that sits at a peak exactly on
    the trim boundary (t = 3.00 s), the worst case for filtfilt: its padding
    assumes the signal has always been at that first value, so a filter started
    there overshoots for about a second. Running every filter on the full
    covered window and trimming afterwards puts that overshoot in the discarded
    region, leaving the first second of the window as quiet as the interior.
    Trimming first re-creates it inside the window (measured +13% std).
    """
    amplitude_ms2 = 3.0

    def peak_on_the_trim_boundary(t):
        return amplitude_ms2 * np.cos(2 * np.pi * 2.0 * t)

    csv_path = drive_csv(duration_s=20.0, speed_mps=BASELINE_SPEED_MPS,
                         a_vert=peak_on_the_trim_boundary)
    log = run_analyze(csv_path, tmp_path / 'out')

    assert 'Edge trim: 300 samples' in log
    assert 'Analysis window: 1400 samples' in log  # 2000 grid samples - 2 * 300

    a_vertical_g = pipeline_signals['a_vertical_g']
    one_second = int(FS)
    interior_std = np.std(a_vertical_g[one_second:-one_second])

    assert interior_std == pytest.approx(amplitude_ms2 / G0 / np.sqrt(2), rel=0.02)
    assert np.std(a_vertical_g[:one_second]) == pytest.approx(interior_std, rel=0.03)
    assert np.std(a_vertical_g[-one_second:]) == pytest.approx(interior_std, rel=0.03)


def test_content_outside_the_analysis_window_never_reaches_the_metrics(drive_csv, tmp_path):
    """
    Steps confined to the first/last 0.6 s are trimmed away before segmentation.

    What survives into the window is the decayed tail of a real event, not a
    start-up artifact, so it must be a small fraction of the step itself.
    """
    step_ms2 = 30.0

    def edge_steps(t):
        a = np.zeros_like(t)
        a[t < 0.6] = step_ms2
        a[t > t[-1] - 0.6] = step_ms2
        return a

    csv_path = drive_csv(duration_s=20.0, speed_mps=BASELINE_SPEED_MPS, a_vert=edge_steps)
    run_analyze(csv_path, tmp_path / 'out')
    df = pd.read_csv(tmp_path / 'out' / 'road_segments.csv')

    assert df['anomaly_count'].sum() == 0, 'a trimmed edge step leaked into anomalies'
    assert df['grms'].max() < 0.01 * step_ms2 / G0, 'a trimmed edge step leaked into Grms'


def test_stationary_drive_reports_uniform_grms_across_segments(baseline_run):
    """
    A stationary excitation must give every full segment the same Grms.

    This is a segmentation sanity check, not the trim regression: the first full
    segment starts 100 m (6.7 s) into the analysis window, far past any filter
    start-up, so a one-second transient cannot show up here. The transient itself
    is pinned on the signal in test_pipeline_trims_filter_edges.
    """
    full = baseline_run['segments'][~baseline_run['segments']['partial']]
    grms = full['grms'].to_numpy()

    assert len(grms) >= 3
    assert grms[0] == pytest.approx(np.median(grms[1:]), rel=0.05)


def test_step_inside_analysis_window_is_still_detected(drive_csv, tmp_path):
    """Control for the trim test: the same step mid-recording must be seen."""
    def mid_step(t):
        a = np.zeros_like(t)
        a[(t >= 9.95) & (t <= 10.05)] = 30.0
        return a

    csv_path = drive_csv(duration_s=20.0, speed_mps=BASELINE_SPEED_MPS, a_vert=mid_step)
    run_analyze(csv_path, tmp_path / 'out')
    df = pd.read_csv(tmp_path / 'out' / 'road_segments.csv')

    assert df['anomaly_count'].sum() > 0
    assert df['grms'].max() > 0.1


# --- Band-pass ----------------------------------------------------------------

def test_pipeline_applies_bandpass_before_metrics(drive_csv, tmp_path):
    """
    A 15 Hz component (outside 0.5-6 Hz) must not inflate Grms.

    Grms of the raw mix would be 0.1486 g; only the 2 Hz component survives the
    band-pass, leaving (0.5/g0)/sqrt(2) = 0.03605 g.
    """
    in_band_ms2, out_of_band_ms2 = 0.5, 2.0

    def two_tone(t):
        return (in_band_ms2 * np.sin(2 * np.pi * 2.0 * t)
                + out_of_band_ms2 * np.sin(2 * np.pi * 15.0 * t))

    csv_path = drive_csv(duration_s=20.0, speed_mps=BASELINE_SPEED_MPS, a_vert=two_tone)
    run_analyze(csv_path, tmp_path / 'out')
    df = pd.read_csv(tmp_path / 'out' / 'road_segments.csv')

    grms_in_band = in_band_ms2 / G0 / np.sqrt(2)
    grms_unfiltered = np.sqrt((in_band_ms2**2 + out_of_band_ms2**2) / 2) / G0

    full = df[~df['partial']]
    assert len(full) >= 1
    assert full['grms'].to_numpy() == pytest.approx(grms_in_band, rel=0.05)
    assert full['grms'].max() < 0.5 * grms_unfiltered


# --- Distress removal (B8) ----------------------------------------------------

def test_distress_windows_are_dropped_from_the_psd_but_kept_in_grms(drive_csv, tmp_path,
                                                                    pipeline_signals):
    """
    A pothole must leave Grms alone and leave the Eq.3 PSD input.

    Eq.3 is calibrated on a signal without major defects, so the +-0.5 s window
    around every anomaly is masked out for the PSD only. The masked samples are
    dropped, never replaced by a fabricated value, so the segment reports fewer
    PSD samples than it has and a scalar measurably below the one the same
    segment would give with the pothole left in.
    """
    def road_with_pothole(t):
        # s = 15 m/s * 17 s = 255 m: mid-segment, so the +-0.5 s mask cannot
        # spill into the neighbouring segment
        a = _baseline_excitation(t)
        a[(t >= 17.0) & (t < 17.05)] += 30.0
        return a

    csv_path = drive_csv(duration_s=40.0, speed_mps=BASELINE_SPEED_MPS,
                         a_vert=road_with_pothole)
    log = run_analyze(csv_path, tmp_path / 'out')
    df = pd.read_csv(tmp_path / 'out' / 'road_segments.csv')

    assert 'Distress removal: 105 samples masked for PSD' in log  # 1 anomaly window

    hit = df[df['anomaly_count'] > 0]
    assert len(hit) == 1, 'the synthetic pothole must fall inside a single segment'
    hit = hit.iloc[0]
    clean = df[(df['anomaly_count'] == 0) & (~df['partial'])]

    # The masked samples are gone from the PSD input, not zero-filled
    assert hit['psd_n_samples_used'] < hit['n_samples']
    assert (clean['psd_n_samples_used'] == clean['n_samples']).all()

    # Grms runs on the unmasked signal, so the pothole is still reported there
    assert hit['grms'] > 3 * clean['grms'].median()

    # ... while the PSD scalar is the one the cleaned run gives, not the raw one
    indices = create_segments(pipeline_signals['s_grid'])[hit['seg_id']]
    *_, with_pothole = compute_iri_psd(
        pipeline_signals['a_vertical_g'][indices], FS,
        f_low=BAND_LOW_HZ, f_high=BAND_HIGH_HZ, return_debug=True
    )
    assert hit['psd_sqrt_scalar'] < 0.98 * with_pothole['psd_sqrt_scalar']
    assert hit['psd_sqrt_scalar'] == pytest.approx(
        clean['psd_sqrt_scalar'].median(), rel=0.05
    )


# --- Reproducibility ----------------------------------------------------------

def test_pipeline_is_deterministic_across_two_runs(baseline_run, tmp_path):
    """Two runs on the same CSV must produce byte-identical segment tables."""
    rerun_dir = tmp_path / 'rerun'
    run_analyze(baseline_run['csv'], rerun_dir)

    first = (baseline_run['out'] / 'road_segments.csv').read_bytes()
    second = (rerun_dir / 'road_segments.csv').read_bytes()
    assert first == second

    assert ((baseline_run['out'] / 'roughness.geojson').read_bytes()
            == (rerun_dir / 'roughness.geojson').read_bytes())


# --- Report content -----------------------------------------------------------

def test_report_documents_actual_iri_multi_coefficients(baseline_run):
    """The report must render the Eq.6 constants the code evaluates."""
    report = baseline_run['report']

    assert '- grms: 50.32' in report
    assert '- speed_kmh: -0.06' in report
    assert '- const: 6.68' in report
    # The superseded, never-executed line
    assert 'a=1.63, b=63.3, c=1.0' not in report


def test_report_documents_eq3_coefficients(baseline_run):
    report = baseline_run['report']

    assert '- A_sqrt_psd = 0.774' in report
    assert '- B_const = -0.825' in report


def test_report_lists_all_generated_artifacts(baseline_run):
    report = baseline_run['report']

    for name in ('road_segments.csv', 'roughness.geojson', 'events.geojson',
                 'segments_map.html', 'plots/'):
        assert name in report


def test_report_reports_dx_and_share_dx_le_03(baseline_run):
    """Spatial-sampling validity must be reported, never silently assumed."""
    report = baseline_run['report']

    assert 'Mean dx: 0.150 m' in report          # v/fs = 15/100
    assert 'Share dx≤0.3m: 100.0%' in report
    assert 'P95 dx:' in report
    assert 'dx_le_03_share' in report


def test_report_records_the_analysis_window(baseline_run):
    report = baseline_run['report']

    assert 'Detected Time unit: ms' in report
    assert 'Edge trim: 300 samples (3 s) per side, applied AFTER filtering' in report
    assert 'Samples used for metrics: 3400' in report  # 4000 grid samples - 2 * 300


# --- Stage C: recording metadata surfaced in report.md + recording_meta.json --

V3_VEHICLE_BLOCK = (
    "# vehicle_type=sedan\n# vehicle_make_model=Skoda Octavia\n# vehicle_year=2019\n"
    "# vehicle_suspension_type=independent\n# vehicle_suspension_condition=good\n"
    "# vehicle_tire_size=205/55 R16\n# vehicle_tire_type=summer\n"
    "# vehicle_tire_pressure_bar=2.3\n# vehicle_load=driver_only\n"
    "# vehicle_mount=windshield\n# vehicle_mount_rigid=true\n"
)
V3_COMMENT_TAIL_EVENTS = (
    "# event: t=1753796581000, type=gps_lost, age_s=12\n"
    "# event: t=1753796576100, type=accuracy_changed, sensor=accel, accuracy=3\n"
)
V3_FOOTER = ("# end: duration_ms=40000, rows_accel=4000, rows_gyro=0, rows_gps=40, "
             "events=2, battery_end_pct=-1, reason=user\n")


def _append_v3_layer(csv_path):
    """Inject the vehicle block before the header and events+footer at EOF."""
    from pathlib import Path
    p = Path(csv_path)
    text = p.read_text(encoding='utf-8')
    text = text.replace("Time,Type,", V3_VEHICLE_BLOCK + "Time,Type,", 1)
    text += V3_COMMENT_TAIL_EVENTS + V3_FOOTER
    p.write_text(text, encoding='utf-8')


def test_analyze_surfaces_v3_metadata(tmp_path, drive_csv):
    import json

    csv_path = drive_csv('v3.csv', duration_s=40.0, a_vert=_baseline_excitation)
    _append_v3_layer(csv_path)
    out = tmp_path / 'out'
    run_analyze(csv_path, out)

    report = (out / 'report.md').read_text(encoding='utf-8')
    assert '## Recording Metadata' in report
    assert 'reason=user' in report            # clean stop verdict
    assert 'недоступно' in report             # battery_end_pct=-1 rendered as unavailable
    assert '## Vehicle Profile' in report and 'Skoda Octavia' in report
    assert '## Recording Events' in report and 'gps_lost' in report
    assert 'accuracy_changed' in report       # counted but excluded from incidents
    assert 'recording_meta.json' in report    # listed among generated artifacts

    meta = json.loads((out / 'recording_meta.json').read_text(encoding='utf-8'))
    assert meta['clean_stop'] is True
    assert meta['vehicle']['vehicle_type'] == 'sedan'
    assert len(meta['events']) == 2
    assert meta['footer']['reason'] == 'user'


def test_analyze_pre_v21_file_reports_absence(tmp_path, drive_csv):
    import json

    csv_path = drive_csv('v2.csv', duration_s=40.0, a_vert=_baseline_excitation,
                         preamble=False)
    out = tmp_path / 'out'
    run_analyze(csv_path, out)

    report = (out / 'report.md').read_text(encoding='utf-8')
    assert '## Recording Metadata' in report
    assert 'обірваний або записаний до контракту v2.1' in report

    meta = json.loads((out / 'recording_meta.json').read_text(encoding='utf-8'))
    assert meta['clean_stop'] is False and meta['vehicle'] == {}
