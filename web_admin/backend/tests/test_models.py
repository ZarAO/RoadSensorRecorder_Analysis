def test_models_roundtrip(tmp_path):
    from src.db.session import make_engine, init_db
    from src.db.models import SourceFile, AnalysisRun
    from sqlalchemy.orm import Session

    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    init_db(engine)
    with Session(engine) as s:
        f = SourceFile(filename='a.csv', size_bytes=10,
                       recording_meta={'vehicle': {'vehicle_type': 'sedan'}})
        f.runs.append(AnalysisRun(params={'low_speed_policy': 'invalid'}))
        s.add(f)
        s.commit()
        assert f.runs[0].status == 'queued'
        assert f.runs[0].file_id == f.id
        assert f.recording_meta['vehicle']['vehicle_type'] == 'sedan'
        assert f.source_deleted is False
        assert f.uploaded_at is not None
