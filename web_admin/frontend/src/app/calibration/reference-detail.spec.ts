import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { GeoJsonFeatureCollection, ReferenceIntervalRow, ReferenceOut } from '../api/dto';
import { SegmentMap } from '../shared/segment-map';
import { ReferenceDetail } from './reference-detail';

const REFERENCE: ReferenceOut = {
  id: 7, filename: 'form25.xlsx', uploaded_at: '2026-08-20T10:00:00Z',
  road_name: 'M-01 km 12-14', direction: 'forward', lane: 1, category: 2,
  step_m: 10, measured_at: '2026-07-01', intervals_count: 3,
  chainage_span_m: 30, bbox: [50.0, 30.0, 50.1, 30.1],
  parse_warnings: ['крок 9.8 м у 3 рядках', 'розривів/перекриттів пікетажу: 1'],
  source_deleted: false, comparisons_count: 2,
};

const GEOJSON: GeoJsonFeatureCollection = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: { interval_id: 0, chainage_m: 5, iri_ref: 2.5 },
    geometry: { type: 'LineString', coordinates: [[30.5, 50.4], [30.51, 50.41]] },
  }],
};

function makeRow(overrides: Partial<ReferenceIntervalRow> = {}): ReferenceIntervalRow {
  return {
    km_start: 0, m_start: 0, km_end: 0, m_end: 10,
    iri_ch1: 1, iri_ch2: 2, iri_ch3: 3, iri_ch4: 4,
    iri_ch5: 5, iri_ch6: 4, iri_ch7: 3, iri_ch8: 2,
    iri_ch9: 2, iri_ch10: 2,
    lat_start: 50, lon_start: 30, alt_start: 100,
    lat_end: 50.001, lon_end: 30.001, alt_end: 100,
    iri_ref: 3,
    ...overrides,
  };
}

const ROWS: ReferenceIntervalRow[] = [
  makeRow({ m_end: 10 }),
  makeRow({ m_start: 10, m_end: 20, iri_ref: null }),
  makeRow({ m_start: 20, m_end: 30 }),
];

const MANY_ROWS: ReferenceIntervalRow[] = Array.from({ length: 1108 },
  (_, index) => makeRow({ m_start: index * 10, m_end: (index + 1) * 10 }));

function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    getReference: () => of(REFERENCE),
    getReferenceGeojson: () => of(GEOJSON),
    getReferenceIntervals: () => of(ROWS),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createPage(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [ReferenceDetail],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } } },
    ],
  });
  return TestBed.createComponent(ReferenceDetail);
}

function clickButton(root: ParentNode, label: string): void {
  const button = Array.from(root.querySelectorAll('button'))
    .find(candidate => candidate.textContent?.trim() === label);
  if (!button) throw new Error(`button «${label}» not found`);
  button.click();
}

describe('ReferenceDetail', () => {
  it('shows the road name and the full warning texts', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('M-01 km 12-14');
    expect(text).toContain('крок 9.8 м у 3 рядках');
    expect(text).toContain('розривів/перекриттів пікетажу: 1');
  });

  it('feeds the geojson into the shared segment map with metricKey iri_ref', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const mapDebug = fixture.debugElement.query(By.directive(SegmentMap));
    expect(mapDebug).toBeTruthy();
    const map = mapDebug.componentInstance as SegmentMap;
    expect(map.metricKey()).toBe('iri_ref');
    expect(map.data()?.features.length).toBe(1);
  });

  it('builds one profile series from the non-null iri_ref rows', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const series = fixture.componentInstance.profileSeries();
    expect(series.length).toBe(1);
    expect(series[0].label).toContain('IRI профілометра');
    expect(series[0].colorVar).toBe('--color-fg');
    // Row 2 has iri_ref: null and must be dropped, not plotted as 0
    expect(series[0].points.length).toBe(2);
  });

  it('renders — for a null iri_ref and the ch1-8 min–max as the channel range', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const rows = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr'));
    expect(rows[0].textContent).toContain('1.00–5.00');
    expect(rows[1].textContent).toContain('—');
  });

  it('renders distinct chainage labels for adjacent 10 m intervals', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    // Row 0 midpoint is 5 m (0.005 km), row 1 is 15 m (0.015 km) — at 2 decimals both
    // round to "0.01"; the table must render 3 decimals so they stay distinguishable.
    const rows = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr'));
    const chainageCells = rows.map(row => row.querySelectorAll('td')[1].textContent?.trim());
    expect(chainageCells[0]).toBe('0.005');
    expect(chainageCells[1]).toBe('0.015');
    expect(chainageCells[0]).not.toBe(chainageCells[1]);
  });

  it('paginates «N–M з K» and shows the remainder on the last page', async () => {
    const fixture = createPage(apiStub({ getReferenceIntervals: () => of(MANY_ROWS) }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.textContent).toContain('1–200 з 1108');
    const nextButton = Array.from(host.querySelectorAll('button'))
      .find(b => b.textContent?.trim().includes('Наступні')) as HTMLButtonElement;
    const prevButton = Array.from(host.querySelectorAll('button'))
      .find(b => b.textContent?.trim().includes('Попередні')) as HTMLButtonElement;
    expect(prevButton.disabled).toBe(true);

    clickButton(host, nextButton.textContent!.trim());
    await fixture.whenStable();
    expect(host.textContent).toContain('201–400 з 1108');

    // Jump to the last page (6 pages total for 1108 rows / 200)
    for (let i = 0; i < 10; i++) {
      clickButton(host, nextButton.textContent!.trim());
      await fixture.whenStable();
    }
    expect(host.textContent).toContain('1001–1108 з 1108');
    expect(nextButton.disabled).toBe(true);
  });
});
