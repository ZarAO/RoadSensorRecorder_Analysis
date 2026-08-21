import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { ArtifactEntry, ComparisonOut, RunOut, SegmentRow } from '../api/dto';
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
  error: null, phone_model: 'samsung SM-S948B', device_id: null, vehicle_id: null,
};

/** Base ApiService stub: every test overrides only what it needs to exercise. */
function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    getRun: () => of(RUN),
    getSegments: () => of(SEGMENTS),
    getArtifactText: (_id: number, name: string) =>
      of(name === 'roughness.geojson' ? GEOJSON : '# report'),
    artifactUrl: (id: number, name: string) => `/api/runs/${id}/artifacts/${name}`,
    logUrl: (id: number) => `/api/runs/${id}/log`,
    listRunArtifacts: () => of([]),
    listComparisons: () => of([]),
    listRuns: () => of([RUN]),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createRunDetail(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [RunDetail],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      { provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: new Map([['id', '5']]) } } },
    ],
  });
  return TestBed.createComponent(RunDetail);
}

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
    const fixture = createRunDetail(apiStub());
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
    const fixture = createRunDetail(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('app-segment-map')).toBeTruthy();
    expect(host.querySelector('iframe')).toBeNull();
    expect(fixture.componentInstance.mapData()?.features.length).toBe(1);
  });

  it('renders a coefficient chip with the set name when the run has calibrated coefficients', async () => {
    const runWithCoefficients: RunOut = {
      ...RUN,
      params: {
        low_speed_policy: 'invalid',
        coefficients: {
          eq3: null,
          eq6_bias: { set_id: 7, name: 'Sedan calibration v2', params: { bias: -1.55 } },
        },
      },
    };
    const fixture = createRunDetail(apiStub({ getRun: () => of(runWithCoefficients) }));
    await fixture.whenStable();

    const chipsText = (fixture.nativeElement as HTMLElement)
      .querySelector('.coeff-chips')?.textContent ?? '';
    expect(chipsText).toContain('Sedan calibration v2');
    expect(chipsText).not.toContain('Книжкові константи');
  });

  it('rounds coefficient params to 3 decimals instead of printing float noise', async () => {
    const runWithCoefficients: RunOut = {
      ...RUN,
      params: {
        low_speed_policy: 'invalid',
        coefficients: {
          eq3: { set_id: 4, name: 'Sedan eq3', params: { A: 6.0000000000000009, B: 0.41 } },
          eq6_bias: { set_id: 7, name: 'Sedan eq6', params: { bias: -1.5499999999999998 } },
        },
      },
    };
    const fixture = createRunDetail(apiStub({ getRun: () => of(runWithCoefficients) }));
    await fixture.whenStable();

    const chipsText = (fixture.nativeElement as HTMLElement)
      .querySelector('.coeff-chips')?.textContent ?? '';
    expect(chipsText).toContain('A=6.000, B=0.410');
    expect(chipsText).toContain('bias=-1.550');
    expect(chipsText).not.toContain('1.5499999');
  });

  it('renders a muted "book constants" chip when the run has no coefficients', async () => {
    const fixture = createRunDetail(apiStub());
    await fixture.whenStable();

    const chipsText = (fixture.nativeElement as HTMLElement)
      .querySelector('.coeff-chips')?.textContent ?? '';
    expect(chipsText).toContain('Книжкові константи');
  });

  it('renders artifact rows with human-readable sizes', async () => {
    const artifacts: ArtifactEntry[] = [
      { name: 'report.md', size_bytes: 10 },
      { name: 'figures/f.png', size_bytes: 20 },
    ];
    const fixture = createRunDetail(apiStub({ listRunArtifacts: () => of(artifacts) }));
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const links = Array.from(host.querySelectorAll('a')).filter(a => artifacts.some(
      artifact => a.textContent?.trim() === artifact.name));
    expect(links.length).toBe(2);
    for (const link of links) {
      expect(link.getAttribute('target')).toBe('_blank');
      const row = link.closest('tr');
      expect(row?.textContent).toContain('KB');
    }
  });

  it('shows the comparisons section only when comparisons exist', async () => {
    const emptyFixture = createRunDetail(apiStub());
    await emptyFixture.whenStable();
    expect((emptyFixture.nativeElement as HTMLElement).textContent)
      .not.toContain('Порівняння з профілометром');

    const comparisons: ComparisonOut[] = [{
      id: 3, run_id: 5, reference_id: 1, run_filename: 'drive.csv',
      reference_road: 'M-01 km 12-14', created_at: '2026-08-20T10:00:00Z',
      status: 'done', params: {}, result_dir: 'x',
      summary: {
        n_pairs: 10, spearman_rho: 0.94, pearson_r: 0.9, mae: 0.5, bias: -1.5,
        n_eff: 10, eq3_r2: null, gates: {},
      },
      error: null,
    }];
    const fixture = createRunDetail(apiStub({ listComparisons: () => of(comparisons) }));
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Порівняння з профілометром');
    expect(text).toContain('M-01 km 12-14');
    expect(text).toContain('0.94');
    const link = (fixture.nativeElement as HTMLElement).querySelector('a[href="/calibration/comparisons/3"]');
    expect(link).toBeTruthy();
  });

  it('adds the corrected IRI column only when a segment carries iri_multi_corrected', async () => {
    const withoutCorrection = createRunDetail(apiStub());
    await withoutCorrection.whenStable();
    expect((withoutCorrection.nativeElement as HTMLElement).textContent)
      .not.toContain('IRI кориг.');

    const correctedSegments: SegmentRow[] = [
      { ...SEGMENTS[0], iri_multi_corrected: 3.0 },
      { ...SEGMENTS[1], iri_multi_corrected: null },
    ];
    const fixture = createRunDetail(apiStub({ getSegments: () => of(correctedSegments) }));
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('IRI кориг.');
    const rows = host.querySelectorAll('tbody tr');
    expect(rows[0].textContent).toContain('3.00');
    expect(rows[1].textContent).toContain('—');
  });

  it('discloses that the map colors stay uncorrected, and shows the corrected mean', async () => {
    const plain = createRunDetail(apiStub());
    await plain.whenStable();
    expect((plain.nativeElement as HTMLElement).querySelector('.corrected-note')).toBeNull();
    expect((plain.nativeElement as HTMLElement).textContent)
      .not.toContain('Середній IRI (кориг.)');

    const correctedRun: RunOut = {
      ...RUN,
      summary: { ...RUN.summary!, mean_iri_multi_corrected: 1.65 },
    };
    const fixture = createRunDetail(apiStub({
      getRun: () => of(correctedRun),
      getSegments: () => of([{ ...SEGMENTS[0], iri_multi_corrected: 3.0 }]),
    }));
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.corrected-note')?.textContent)
      .toContain('Кольори мапи — за некоригованим IRI_multi');
    expect(host.textContent).toContain('Середній IRI (кориг.)');
    expect(host.textContent).toContain('1.65');
  });

  it('hides the compare button when the file has fewer than 2 done runs', async () => {
    const fixture = createRunDetail(apiStub({ listRuns: () => of([RUN]) }));
    await fixture.whenStable();

    const buttons = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'));
    expect(buttons.some(b => b.textContent?.trim() === 'Порівняти з іншим раном')).toBe(false);
  });

  it('shows the compare button and navigates to the chosen run when the file has another done run', async () => {
    const otherRun: RunOut = { ...RUN, id: 9 };
    const fixture = createRunDetail(apiStub({ listRuns: () => of([RUN, otherRun]) }));
    await fixture.whenStable();
    const navigateSpy = vi.spyOn(TestBed.inject(Router), 'navigate');

    const host = fixture.nativeElement as HTMLElement;
    const button = Array.from(host.querySelectorAll('button'))
      .find(b => b.textContent?.trim() === 'Порівняти з іншим раном');
    expect(button).toBeTruthy();
    button!.click();
    await fixture.whenStable();

    const dialog = host.querySelector('.dialog');
    expect(dialog).toBeTruthy();
    const options = Array.from(dialog!.querySelectorAll<HTMLOptionElement>('option')).map(o => o.value);
    expect(options).toEqual(['9']);

    const submit = Array.from(dialog!.querySelectorAll('button'))
      .find(b => b.textContent?.trim() === 'Порівняти');
    submit!.click();
    expect(navigateSpy).toHaveBeenCalledWith(['/runs', 5, 'compare', 9]);
  });

  it('never offers itself as a compare target when the file has 3 done runs', async () => {
    const otherA: RunOut = { ...RUN, id: 9 };
    const otherB: RunOut = { ...RUN, id: 12 };
    const fixture = createRunDetail(apiStub({ listRuns: () => of([RUN, otherA, otherB]) }));
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const button = Array.from(host.querySelectorAll('button'))
      .find(b => b.textContent?.trim() === 'Порівняти з іншим раном');
    button!.click();
    await fixture.whenStable();

    const options = Array.from(host.querySelectorAll<HTMLOptionElement>('.dialog option')).map(o => o.value);
    expect(options).toEqual(['9', '12']);
  });
});
