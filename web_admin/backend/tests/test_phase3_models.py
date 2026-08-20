from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


def test_phase3_models_roundtrip(tmp_path):
    from src.db.session import make_engine, init_db
    from src.db.models import (AnalysisRun, Comparison, CoefficientSet,
                               ReferenceDataset, SourceFile)
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with Session(engine) as s:
        ref = ReferenceDataset(filename='f.xlsx', road_name='Т1016', step_m=10.0,
                               intervals_count=164, chainage_span_m=1640.0,
                               bbox=[50.1, 30.1, 50.4, 30.9], parse_warnings=[])
        f = SourceFile(filename='a.csv', size_bytes=1)
        s.add_all([ref, f]); s.commit()
        run = AnalysisRun(file_id=f.id)
        cs = CoefficientSet(name='UA_test', model='eq6_bias', params={'bias': -1.55},
                            vehicle_type='van', phone_model='samsung SM-S948B')
        s.add_all([run, cs]); s.commit()
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit()
        assert cmp_.reference.road_name == 'Т1016'
        assert cmp_.run.id == run.id
        run.eq6_bias_set_id = cs.id; s.commit()
        assert s.get(AnalysisRun, run.id).eq6_bias_set_id == cs.id


def test_init_db_migrates_existing_runs_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY, file_id INTEGER)'))
    from src.db.session import init_db
    init_db(engine)
    cols = {col['name'] for col in inspect(engine).get_columns('analysis_runs')}
    assert {'eq3_set_id', 'eq6_bias_set_id'} <= cols
    init_db(engine)  # idempotent


def test_reference_dir_setting(tmp_path, monkeypatch):
    from src.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv('RQA_REFERENCE_DIR', str(tmp_path / 'ref'))
    assert get_settings().storage_reference_dir == tmp_path / 'ref'
    get_settings.cache_clear()
