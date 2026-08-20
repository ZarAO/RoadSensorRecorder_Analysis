import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { RunOut, SegmentRow } from '../api/dto';
import { RunDetail } from './run-detail';

const RUN: RunOut = {
  id: 5, file_id: 1, filename: 'drive.csv',
  created_at: '2026-08-20T10:00:00Z', started_at: '2026-08-20T10:00:01Z',
  finished_at: '2026-08-20T10:00:30Z', status: 'done',
  params: { low_speed_policy: 'invalid' }, result_dir: 'x',
  summary: {
    segments_total: 2, km_total: 0.2, mean_iri_multi: 3.2, low_speed_count: 1,
    partial_count: 0, events_total: 2, incidents_total: 1, clean_stop: true,
    vehicle_type: 'sedan',
  },
  error: null,
};

const SEGMENTS: SegmentRow[] = [
  { seg_id: 0, s_start: 0, s_end: 100, length_m: 100, grms: 0.01,
    iri_psd_raw: 2, iri_psd: 2, iri_multi: 3.2, mean_speed_kmh: 45,
    events_per_km: 0, partial: false, speed_valid: true,
    low_speed_class: null, needs_class12_survey: false },
  { seg_id: 1, s_start: 100, s_end: 200, length_m: 100, grms: 0.02,
    iri_psd_raw: 2.5, iri_psd: 2.5, iri_multi: null, mean_speed_kmh: 12,
    events_per_km: 30, partial: false, speed_valid: false,
    low_speed_class: 'invalid', needs_class12_survey: true },
];

const GEOJSON = JSON.stringify({
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: { seg_id: 0, iri_multi: 3.2, filename: 'drive.csv' },
    geometry: { type: 'LineString', coordinates: [[30.5, 50.4], [30.51, 50.41]] },
  }],
});

describe('RunDetail', () => {
  it('never renders a numeric IRI for a low-speed segment', async () => {
    const api = {
      getRun: () => of(RUN),
      getSegments: () => of(SEGMENTS),
      getArtifactText: (_id: number, name: string) =>
        of(name === 'roughness.geojson' ? GEOJSON : '# report'),
      artifactUrl: (id: number, name: string) => `/api/runs/${id}/artifacts/${name}`,
      logUrl: (id: number) => `/api/runs/${id}/log`,
    } as Partial<ApiService> as ApiService;

    TestBed.configureTestingModule({
      imports: [RunDetail],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: api },
        { provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['id', '5']]) } } },
      ],
    });
    const fixture = TestBed.createComponent(RunDetail);
    await fixture.whenStable();

    const rows = (fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    const lowSpeedRow = rows[1].textContent ?? '';
    expect(lowSpeedRow).toContain('невалідна швидкість');
    expect(lowSpeedRow).not.toContain('null');
    // The numeric iri_multi of the valid row appears; the low-speed row shows a dash
    expect(rows[0].textContent).toContain('3.2');
    expect(lowSpeedRow).toContain('—');
  });

  it('feeds roughness.geojson into the shared segment map', async () => {
    const api = {
      getRun: () => of(RUN),
      getSegments: () => of(SEGMENTS),
      getArtifactText: (_id: number, name: string) =>
        of(name === 'roughness.geojson' ? GEOJSON : '# report'),
      artifactUrl: (id: number, name: string) => `/api/runs/${id}/artifacts/${name}`,
      logUrl: (id: number) => `/api/runs/${id}/log`,
    } as Partial<ApiService> as ApiService;

    TestBed.configureTestingModule({
      imports: [RunDetail],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: api },
        { provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map([['id', '5']]) } } },
      ],
    });
    const fixture = TestBed.createComponent(RunDetail);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('app-segment-map')).toBeTruthy();
    expect(host.querySelector('iframe')).toBeNull();
    expect(fixture.componentInstance.mapData()?.features.length).toBe(1);
  });
});
