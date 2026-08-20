from tests.test_runs_api import fake_analyze, make_done_run  # noqa: F401 (fixtures)


def test_artifact_served_and_traversal_blocked(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    r = client.get(f'/api/runs/{rid}/artifacts/report.md')
    assert r.status_code == 200 and '# ok' in r.text
    assert client.get(f'/api/runs/{rid}/artifacts/..%2F..%2Fsecret').status_code in (403, 404)
    assert client.get(f'/api/runs/{rid}/artifacts/nope.png').status_code == 404


def test_segments_json_serializes_nan_as_null(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    rows = client.get(f'/api/runs/{rid}/segments').json()
    assert len(rows) == 2
    assert rows[0]['iri_multi'] == 3.2
    assert rows[1]['iri_multi'] is None          # NaN -> null, never a number
    assert rows[1]['needs_class12_survey'] is True


def test_log_plain(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    r = client.get(f'/api/runs/{rid}/log?follow=false')
    assert r.status_code == 200 and 'progress line' in r.text


def test_log_sse_of_finished_run_ends(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    with client.stream('GET', f'/api/runs/{rid}/log') as r:
        assert r.status_code == 200
        assert 'text/event-stream' in r.headers['content-type']
        body = ''.join(r.iter_text())
    assert 'progress line' in body
