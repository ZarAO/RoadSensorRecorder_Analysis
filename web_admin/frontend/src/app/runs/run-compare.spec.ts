import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ApiService } from '../api/api.service';
import { FileCompareOut, RunOut } from '../api/dto';
import { RunCompare } from './run-compare';

const RUN_A: RunOut = {
  id: 5, file_id: 1, filename: 'drive.csv', created_at: '2026-08-20T10:00:00Z',
  started_at: null, finished_at: null, status: 'done',
  params: { low_speed_policy: 'invalid' }, result_dir: 'x', summary: null,
  error: null, phone_model: null, device_id: null, vehicle_id: null,
};

const COMPARE: FileCompareOut = {
  file_id: 1,
  run_a: { id: 5, params: { low_speed_policy: 'invalid' }, summary: null },
  run_b: {
    id: 6,
    params: {
      low_speed_policy: 'poor',
      coefficients: { eq3: null, eq6_bias: { set_id: 7, name: 'Sedan bias', params: { bias: -1.55 } } },
    },
    summary: null,
  },
  segments: [
    { seg_id: 0, s_start: 0, iri_multi_a: 3.0, iri_multi_b: 3.2, delta_iri_multi: 0.2,
      iri_psd_a: 2.0, iri_psd_b: 2.1, grms_a: 0.5, grms_b: 0.51,
      mean_speed_a: 50, mean_speed_b: 48 },
    { seg_id: 1, s_start: 100, iri_multi_a: 4.0, iri_multi_b: 5.0, delta_iri_multi: 1.0,
      iri_psd_a: 3.0, iri_psd_b: 3.5, grms_a: 0.6, grms_b: 0.7,
      mean_speed_a: 55, mean_speed_b: 52 },
    { seg_id: 2, s_start: 200, iri_multi_a: 4.5, iri_multi_b: null, delta_iri_multi: null,
      iri_psd_a: 2.8, iri_psd_b: null, grms_a: 0.55, grms_b: null,
      mean_speed_a: 40, mean_speed_b: null },
  ],
  summary: { segments: 3, matched: 3, mean_delta_iri_multi: 0.6, max_abs_delta: 1.0 },
};

function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    getRun: () => of(RUN_A),
    compareRuns: () => of(COMPARE),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createPage(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [RunCompare],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: '5', other: '6' }) } },
      },
    ],
  });
  return TestBed.createComponent(RunCompare);
}

describe('RunCompare', () => {
  it('fetches the comparison via the run A file_id and the two route ids', async () => {
    const compareSpy = vi.fn(() => of(COMPARE));
    const fixture = createPage(apiStub({
      compareRuns: compareSpy as unknown as ApiService['compareRuns'],
    }));
    await fixture.whenStable();

    expect(compareSpy).toHaveBeenCalledWith(1, 5, 6);
  });

  it('renders the deltas and highlights |delta_iri_multi| > 0.5 rows', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const rows = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll('#segments-table tbody tr'));
    expect(rows.length).toBe(3);
    expect(rows[0].textContent).toContain('0.20');
    expect(rows[0].classList.contains('hot')).toBe(false);
    expect(rows[1].textContent).toContain('1.00');
    expect(rows[1].classList.contains('hot')).toBe(true);
  });

  it('shows a null-safe dash for a null delta (low-speed invariant)', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const rows = (fixture.nativeElement as HTMLElement)
      .querySelectorAll('#segments-table tbody tr');
    const lastRow = rows[2];
    expect(lastRow.classList.contains('hot')).toBe(false);
    const cells = Array.from(lastRow.querySelectorAll('td')).map(td => td.textContent?.trim());
    expect(cells).toEqual(['2', '200', '4.50', '—', '—', '2.80', '—', '0.5500', '—', '40.0', '—']);
  });

  it('shows the summary KPIs', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('сегментів');
    expect(host.textContent).toContain('співставлено');
    const cards = Array.from(host.querySelectorAll('.kpi-card b'));
    expect(cards.map(c => c.textContent?.trim())).toEqual(['3', '3', '0.60', '1.00']);
  });

  it('renders a coefficient chip for run B and the book-constants chip for run A', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const chipRows = host.querySelectorAll('.coeff-chips');
    expect(chipRows[0].textContent).toContain('Книжкові константи');
    expect(chipRows[1].textContent).toContain('Sedan bias');
  });

  it('shows the low_speed_policy for each side', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('invalid');
    expect(host.textContent).toContain('poor');
  });

  it('labels the segment columns as corrected and shows the effective-value hint '
    + 'when a side carries an eq6_bias snapshot', async () => {
    const fixture = createPage(apiStub()); // COMPARE.run_b carries eq6_bias
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const headers = Array.from(host.querySelectorAll('#segments-table thead th'))
      .map(th => th.textContent?.trim());
    expect(headers).toContain('IRI кориг. A');
    expect(headers).toContain('IRI кориг. B');
    expect(headers).not.toContain('IRI_multi A');
    expect(headers).not.toContain('IRI_multi B');
    expect(host.querySelector('.corrected-note')?.textContent).toContain('IRI кориг.');
  });

  it('hides the effective-value hint when neither run carries an eq6_bias snapshot', async () => {
    const noBias: FileCompareOut = {
      ...COMPARE,
      run_b: { ...COMPARE.run_b, params: { low_speed_policy: 'poor' } },
    };
    const fixture = createPage(apiStub({ compareRuns: () => of(noBias) }));
    await fixture.whenStable();

    expect((fixture.nativeElement as HTMLElement).querySelector('.corrected-note')).toBeNull();
  });

  it('shows an error banner when the compare request fails', async () => {
    const fixture = createPage(apiStub({
      compareRuns: (() => throwError(
        () => ({ error: { detail: 'обидва рани мають бути завершені' } }),
      )) as unknown as ApiService['compareRuns'],
    }));
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.error-banner')?.textContent)
      .toContain('обидва рани мають бути завершені');
    expect(host.querySelector('#segments-table')).toBeFalsy();
  });

  it('stringifies a FastAPI 422 array detail instead of printing [object Object]', async () => {
    const fixture = createPage(apiStub({
      compareRuns: (() => throwError(() => ({
        error: {
          detail: [
            { type: 'int_parsing', loc: ['query', 'run_a'], msg: 'Input should be a valid integer' },
          ],
        },
      }))) as unknown as ApiService['compareRuns'],
    }));
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).querySelector('.error-banner')?.textContent ?? '';
    expect(text).toContain('Input should be a valid integer');
    expect(text).not.toContain('[object Object]');
  });
});
