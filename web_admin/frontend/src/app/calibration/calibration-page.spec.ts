import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';

import { ApiService } from '../api/api.service';
import { CoefficientSetOut, ComparisonOut, ConfirmOut, ReferenceOut, RunOut } from '../api/dto';
import { CalibrationPage } from './calibration-page';

const REFERENCE: ReferenceOut = {
  id: 1, filename: 'form25.xlsx', uploaded_at: '2026-08-20T10:00:00Z',
  road_name: 'M-01 km 12-14', direction: 'forward', lane: 1, category: 2,
  step_m: 10, measured_at: '2026-07-01', intervals_count: 20,
  chainage_span_m: 2000, bbox: null, parse_warnings: ['крок 9.8 м', 'пропуск пікету'],
  source_deleted: false, comparisons_count: 1,
};

const RUN: RunOut = {
  id: 5, file_id: 1, filename: 'drive.csv',
  created_at: '2026-08-20T10:00:00Z', started_at: '2026-08-20T10:00:01Z',
  finished_at: '2026-08-20T10:00:30Z', status: 'done',
  params: { low_speed_policy: 'invalid' }, result_dir: 'x',
  summary: null, error: null,
};

const COMPARISON: ComparisonOut = {
  id: 3, run_id: 5, reference_id: 1, run_filename: 'drive.csv',
  reference_road: 'M-01 km 12-14', created_at: '2026-08-20T10:05:00Z',
  status: 'done', params: {}, result_dir: 'x',
  summary: {
    n_pairs: 20, spearman_rho: 0.94, pearson_r: 0.9, mae: 1.2, bias: -1.55,
    n_eff: 18, eq3_r2: null, gates: {},
  },
  error: null,
};

const DRAFT_SET: CoefficientSetOut = {
  id: 9, name: 'Sedan eq6 v1', model: 'eq6_bias', params: { bias: -1.55 },
  vehicle_type: 'sedan', phone_model: null, status: 'draft', comparison_id: 3,
  stats_snapshot: {
    r2: 0.41, mae: 1.2, spearman_rho: 0.94, n_pairs: 20, mae_bias_corrected: 0.8,
  },
  created_at: '2026-08-20T10:10:00Z', confirmed_at: null, confirmed_note: null,
};

const CONFIRM_OUT: ConfirmOut = {
  set: { ...DRAFT_SET, status: 'confirmed' },
  archived_set_id: null,
  reanalyze_candidates: 2,
};

/** Base ApiService stub: every test overrides only what it needs to exercise. */
function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    listReferences: () => of([REFERENCE]),
    listComparisons: () => of([COMPARISON]),
    listCoefficientSets: () => of([DRAFT_SET]),
    listRuns: () => of([RUN]),
    uploadReference: () => of(REFERENCE),
    deleteReference: () => of(void 0),
    createComparison: () => of(COMPARISON),
    deleteComparison: () => of(void 0),
    confirmCoefficientSet: () => of(CONFIRM_OUT),
    archiveCoefficientSet: () => of(DRAFT_SET),
    reanalyzeCoefficientSet: () => of([RUN, RUN]),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createPage(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [CalibrationPage],
    providers: [provideRouter([]), { provide: ApiService, useValue: api }],
  });
  return TestBed.createComponent(CalibrationPage);
}

function click(root: ParentNode, label: string): void {
  const button = Array.from(root.querySelectorAll('button'))
    .find(candidate => candidate.textContent?.trim() === label);
  if (!button) throw new Error(`button «${label}» not found`);
  button.click();
}

describe('CalibrationPage', () => {
  it('renders the three sections', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Еталони профілометра');
    expect(text).toContain('Порівняння');
    expect(text).toContain('Набори коефіцієнтів');
  });

  it('confirms a draft set and offers reanalysis of the matching runs', async () => {
    const confirmSpy = vi.fn(() => of(CONFIRM_OUT));
    const reanalyzeSpy = vi.fn(() => of([RUN, RUN]));
    const fixture = createPage(apiStub({
      confirmCoefficientSet: confirmSpy as unknown as ApiService['confirmCoefficientSet'],
      reanalyzeCoefficientSet: reanalyzeSpy as unknown as ApiService['reanalyzeCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Підтвердити');
    await fixture.whenStable();

    const dialog = host.querySelector('#confirm-dialog');
    expect(dialog).toBeTruthy();
    const note = dialog!.querySelector('textarea') as HTMLTextAreaElement;
    note.value = 'note';
    note.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    click(dialog!.querySelector('.dialog-actions')!, 'Підтвердити');
    await fixture.whenStable();
    expect(confirmSpy).toHaveBeenCalledWith(9, 'note');

    const reanalyze = host.querySelector('#reanalyze-dialog');
    expect(reanalyze).toBeTruthy();
    expect(reanalyze!.textContent).toContain('2');
    expect(reanalyze!.textContent).toContain('sedan');

    click(reanalyze!.querySelector('.dialog-actions')!, 'Перерахувати');
    await fixture.whenStable();
    expect(reanalyzeSpy).toHaveBeenCalledWith(9);
    expect((fixture.nativeElement as HTMLElement).textContent)
      .toContain('Створено 2 нових ранів');
  });

  it('shows the parse-warning count of a reference row', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const row = (fixture.nativeElement as HTMLElement)
      .querySelector('#references-table tbody tr');
    expect(row?.textContent).toContain('2 попередж.');
    expect(row?.querySelector('[title]')?.getAttribute('title'))
      .toContain('пропуск пікету');
  });

  it('closes the comparison dialog immediately on submit, before the response arrives', async () => {
    const pending = new Subject<ComparisonOut>();
    const createSpy = vi.fn(() => pending.asObservable());
    const fixture = createPage(apiStub({
      createComparison: createSpy as unknown as ApiService['createComparison'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Нове порівняння');
    await fixture.whenStable();
    expect(host.querySelector('#comparison-dialog')).toBeTruthy();

    click(host.querySelector('#comparison-dialog')!.querySelector('.dialog-actions')!, 'Порівняти');
    await fixture.whenStable();

    // Dialog is gone right away, so a second click can't reach the button —
    // the request is still pending (pending.next() was never called).
    expect(host.querySelector('#comparison-dialog')).toBeFalsy();
    expect(createSpy).toHaveBeenCalledTimes(1);

    pending.next(COMPARISON);
    pending.complete();
    await fixture.whenStable();
  });

  it('guards reanalyze against a double click: the second one creates no runs', async () => {
    const pending = new Subject<RunOut[]>();
    const reanalyzeSpy = vi.fn(() => pending.asObservable());
    const fixture = createPage(apiStub({
      reanalyzeCoefficientSet: reanalyzeSpy as unknown as ApiService['reanalyzeCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Підтвердити');
    await fixture.whenStable();
    click(host.querySelector('#confirm-dialog')!.querySelector('.dialog-actions')!, 'Підтвердити');
    await fixture.whenStable();

    const actions = host.querySelector('#reanalyze-dialog')!.querySelector('.dialog-actions')!;
    click(actions, 'Перерахувати');
    await fixture.whenStable();

    // Dialog stays open while the request is in flight — the button must be
    // disabled, and a second click must not queue another N analyzer runs.
    const button = Array.from(actions.querySelectorAll('button'))
      .find(candidate => candidate.textContent?.trim() === 'Перерахувати')!;
    expect(button.disabled).toBe(true);
    button.click();
    await fixture.whenStable();
    expect(reanalyzeSpy).toHaveBeenCalledTimes(1);

    pending.next([RUN, RUN]);
    pending.complete();
    await fixture.whenStable();
    expect(host.querySelector('#reanalyze-dialog')).toBeFalsy();
  });

  it('keeps the reanalyze dialog open and shows the error banner when reanalyze fails', async () => {
    const reanalyzeSpy = vi.fn(() => throwError(() => ({ error: { detail: 'ран не знайдено' } })));
    const fixture = createPage(apiStub({
      reanalyzeCoefficientSet: reanalyzeSpy as unknown as ApiService['reanalyzeCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Підтвердити');
    await fixture.whenStable();
    click(host.querySelector('#confirm-dialog')!.querySelector('.dialog-actions')!, 'Підтвердити');
    await fixture.whenStable();

    const reanalyze = host.querySelector('#reanalyze-dialog');
    expect(reanalyze).toBeTruthy();

    click(reanalyze!.querySelector('.dialog-actions')!, 'Перерахувати');
    await fixture.whenStable();

    expect(reanalyzeSpy).toHaveBeenCalledWith(9);
    // The offer to retry is still there, and the failure is visible.
    expect(host.querySelector('#reanalyze-dialog')).toBeTruthy();
    expect(host.querySelector('.error-banner')?.textContent).toContain('ран не знайдено');
  });
});
