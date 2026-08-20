"""
Unit tests for the CSV v2.1/v3 comment-layer parser.

Canonical contract: RoadSensorRecorder/README.md (v2 preamble, v2.1 event/footer
lines, v3 vehicle block). Every tolerated irregularity must surface as a warning,
never an exception.
"""

from road_quality_analyzer.io import parse_recording_metadata

V3_PREAMBLE = (
    "# schema=2\n"
    "# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, "
    "time=ms epoch anchored monotonic\n"
    "# anchor: elapsedRealtimeNanos=1000000000, currentTimeMillis=1753796576000\n"
    "# device: SYNTHETIC TEST, android=14\n"
    "# nominal_rate_hz=100\n"
    "# app_version=1.1\n"
    "# battery_start_pct=87\n"
)
VEHICLE_BLOCK = (
    "# vehicle_type=sedan\n"
    "# vehicle_make_model=Skoda Octavia\n"
    "# vehicle_year=2019\n"
    "# vehicle_suspension_type=independent\n"
    "# vehicle_suspension_condition=good\n"
    "# vehicle_tire_size=205/55 R16\n"
    "# vehicle_tire_type=summer\n"
    "# vehicle_tire_pressure_bar=2.3\n"
    "# vehicle_load=driver_only\n"
    "# vehicle_mount=windshield\n"
    "# vehicle_mount_rigid=true\n"
)
HEADER = "Time,Type,X,Y,Z,Latitude,Longitude\n"
ROWS = (
    "1753796576000,Accelerometer,0.0,0.0,9.81,,\n"
    "1753796576010,Accelerometer,0.0,0.0,9.81,,\n"
)
FOOTER = (
    "# end: duration_ms=20000, rows_accel=2000, rows_gyro=0, rows_gps=20, "
    "events=3, battery_end_pct=85, reason=user\n"
)


def write(tmp_path, text, name="rec.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_full_v3_file_parses_everything(tmp_path):
    text = (V3_PREAMBLE + VEHICLE_BLOCK + HEADER + ROWS
            + "# event: t=1753796576500, type=gps_lost, age_s=12\n" + ROWS + FOOTER)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.schema == 2
    assert meta.preamble["device"] == "SYNTHETIC TEST, android=14"
    assert meta.preamble["battery_start_pct"] == "87"
    assert len(meta.vehicle) == 11
    assert meta.vehicle["vehicle_type"] == "sedan"
    assert [e.type for e in meta.events] == ["gps_lost"]
    assert meta.events[0].t_ms == 1753796576500
    assert meta.events[0].attrs == {"age_s": "12"}
    assert meta.footer["reason"] == "user"
    assert meta.clean_stop and meta.footer_count == 1 and meta.warnings == []


def test_bare_file_without_comments(tmp_path):
    meta = parse_recording_metadata(write(tmp_path, HEADER + ROWS))
    assert meta.schema is None and meta.preamble == {} and meta.vehicle == {}
    assert meta.events == [] and meta.footer is None
    assert not meta.clean_stop and meta.warnings == []


def test_optional_tire_pressure_absent(tmp_path):
    block = VEHICLE_BLOCK.replace("# vehicle_tire_pressure_bar=2.3\n", "")
    meta = parse_recording_metadata(write(tmp_path, V3_PREAMBLE + block + HEADER + ROWS))
    assert len(meta.vehicle) == 10 and "vehicle_tire_pressure_bar" not in meta.vehicle


def test_value_split_on_first_equals_only(tmp_path):
    text = V3_PREAMBLE + "# vehicle_make_model=Tesla Model=S\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_make_model"] == "Tesla Model=S"


def test_crlf_double_space_preserved(tmp_path):
    # The recorder replaces \r and \n with one space each, so free text may
    # contain double spaces the parser must not collapse
    text = V3_PREAMBLE + "# vehicle_make_model=Skoda  Octavia\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_make_model"] == "Skoda  Octavia"


def test_unknown_enum_token_warns_but_keeps_value(tmp_path):
    text = V3_PREAMBLE + "# vehicle_type=spaceship\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_type"] == "spaceship"
    assert any("spaceship" in w for w in meta.warnings)


def test_events_sorted_by_t(tmp_path):
    # Contract: event lines are not strictly monotonic vs data rows — sort by t
    text = (V3_PREAMBLE + HEADER + ROWS
            + "# event: t=1753796576900, type=sensor_recovered, sensor=accel, gap_ms=2500\n"
            + "# event: t=1753796576400, type=sensor_stall, sensor=accel, gap_ms=2500\n"
            + ROWS)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert [e.type for e in meta.events] == ["sensor_stall", "sensor_recovered"]


def test_unknown_event_type_kept(tmp_path):
    text = V3_PREAMBLE + HEADER + "# event: t=1753796576400, type=solar_flare\n" + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.events[0].type == "solar_flare"


def test_duplicate_footer_last_wins_with_warning(tmp_path):
    second = FOOTER.replace("reason=user", "reason=destroy")
    meta = parse_recording_metadata(
        write(tmp_path, V3_PREAMBLE + HEADER + ROWS + FOOTER + second))
    assert meta.footer["reason"] == "destroy" and meta.footer_count == 2
    assert any("end" in w.lower() for w in meta.warnings)


def test_battery_unavailable_minus_one(tmp_path):
    text = (V3_PREAMBLE.replace("battery_start_pct=87", "battery_start_pct=-1")
            + HEADER + ROWS + FOOTER.replace("battery_end_pct=85", "battery_end_pct=-1"))
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.preamble["battery_start_pct"] == "-1"
    assert meta.footer["battery_end_pct"] == "-1"


def test_incident_count_excludes_accuracy_changed(tmp_path):
    text = (V3_PREAMBLE + HEADER
            + "# event: t=1753796576100, type=accuracy_changed, sensor=accel, accuracy=3\n"
            + "# event: t=1753796576400, type=gps_lost, age_s=11\n" + ROWS)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert len(meta.events) == 2 and meta.incident_count == 1


def test_garbage_comment_line_warns_and_continues(tmp_path):
    text = V3_PREAMBLE + "# what is this line\n" + HEADER + ROWS + FOOTER
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.clean_stop and any("line" in w.lower() for w in meta.warnings)
