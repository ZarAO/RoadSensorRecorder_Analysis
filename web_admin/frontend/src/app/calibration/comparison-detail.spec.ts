import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ApiService } from '../api/api.service';
import { ChartData, CoefficientSetOut, ComparisonOut, RunOut } from '../api/dto';
import { ComparisonDetail } from './comparison-detail';

const COMPARISON: ComparisonOut = {
  id: 3, run_id: 5, reference_id: 1, run_filename: 'drive.csv',
  reference_road: 'M-01 km 12-14', created_at: '2026-08-20T10:05:00Z',
  status: 'done', params: {}, result_dir: 'x',
  summary: {
    n_pairs: 3, spearman_rho: 0.94, pearson_r: 0.9, mae: 1.37, bias: -1.55,
    n_eff: 2.4, eq3_r2: 0.41, gates: {},
  },
  error: null,
};

const RUN: RunOut = {
  id: 5, file_id: 1, filename: 'drive.csv', created_at: '2026-08-20T10:00:00Z',
  started_at: null, finished_at: null, status: 'done', params: {}, result_dir: 'x',
  summary: {
    segments_total: 3, km_total: 0.3, mean_iri_multi: 5.1, low_speed_count: 0,
    partial_count: 0, events_total: 0, incidents_total: 0, clean_stop: true,
    vehicle_type: 'sedan',
  },
  error: null, phone_model: 'samsung SM-S948B',
};

/** diffs: seg 1 → +1.4, seg 2 → +0.2, seg 3 → −2.5 (sorted table: 3, 1, 2) */
const CHART: ChartData = {
  scatter: [
    { seg_id: 1, psd_sqrt_scalar: 0.010, iri_ref: 2.0, iri_multi: 3.4, chainage_m: 0 },
    { seg_id: 2, psd_sqrt_scalar: 0.020, iri_ref: 3.5, iri_multi: 3.7, chainage_m: 100 },
    { seg_id: 3, psd_sqrt_scalar: 0.030, iri_ref: 5.0, iri_multi: 2.5, chainage_m: 250 },
  ],
  profile: [
    { chainage_m: 0, iri_ref: 2.0, iri_multi: 3.4, iri_multi_bias_corrected: 4.95, seg_id: 1 },
    { chainage_m: 100, iri_ref: 3.5, iri_multi: 3.7, iri_multi_bias_corrected: 5.25, seg_id: 2 },
    { chainage_m: 250, iri_ref: 5.0, iri_multi: 2.5, iri_multi_bias_corrected: 4.05, seg_id: 3 },
  ],
  bland_altman: [
    { seg_id: 1, mean: 2.7, diff: 1.4 },
    { seg_id: 2, mean: 3.6, diff: 0.2 },
    { seg_id: 3, mean: 3.75, diff: -2.5 },
  ],
  eq3_fit: { A: 146.23, B: -1.87, r2: 0.41, mae: 1.2, n: 3 },
  bias: -1.55,
  gates: {},
};

const CREATED_SET: CoefficientSetOut = {
  id: 11, name: 'eq3_sedan_2026-08-20', model: 'eq3', params: { A: 146.23, B: -1.87 },
  vehicle_type: 'sedan', phone_model: null, status: 'draft', comparison_id: 3,
  aggregate_comparison_id: null, stats_snapshot: null, created_at: '2026-08-20T11:00:00Z',
  confirmed_at: null, confirmed_note: null,
};

function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    getComparison: () => of(COMPARISON),
    getComparisonChartData: () => of(CHART),
    getRun: () => of(RUN),
    comparisonArtifactUrl: (id: number, name: string) => `/api/comparisons/${id}/artifacts/${name}`,
    createCoefficientSet: () => of(CREATED_SET),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createPage(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [ComparisonDetail],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: '3' }) } },
      },
    ],
  });
  return TestBed.createComponent(ComparisonDetail);
}

function click(root: ParentNode, label: string): void {
  const button = Array.from(root.querySelectorAll('button'))
    .find(candidate => candidate.textContent?.trim() === label);
  if (!button) throw new Error(`button «${label}» not found`);
  button.click();
}

describe('ComparisonDetail', () => {
  beforeEach(() => {
    // CountUp renders its final value straight away under reduced motion,
    // so the KPI numbers are assertable without waiting for rAF frames.
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: true, media: query, onchange: null,
      addEventListener: () => undefined, removeEventListener: () => undefined,
      addListener: () => undefined, removeListener: () => undefined,
      dispatchEvent: () => false,
    }));
  });

  it('shows the KPI row with the Spearman rho', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const cards = Array.from(host.querySelectorAll('.kpi-card'));
    expect(cards.length).toBe(6);
    const rho = cards.find(card => card.textContent?.includes('ρ Спірмена'));
    expect(rho?.textContent).toMatch(/0[.,]94/);
    expect(host.textContent).toContain('n_eff');
  });

  it('renders both gate chips as indicators, not a decision', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const chips = Array.from(host.querySelectorAll('#gates .chip'));
    expect(chips.length).toBe(2);
    // r2 = 0.41 < 0.85 and corrected MAE = mean(|diff - bias|) = 1.883 > 0.5
    expect(chips[0].textContent?.replace(/\s+/g, ' ').trim()).toBe('R² 0.41 < 0.85');
    expect(chips[0].classList.contains('warn')).toBe(true);
    expect(chips[1].textContent).toContain('> 0.5');
    expect(host.querySelector('#gates .hint')?.textContent)
      .toContain('Індикатори, не автоматичне рішення');
  });

  it('renders the three charts and the substituted formulas', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('app-scatter-chart')).toBeTruthy();
    expect(host.querySelector('app-profile-chart')).toBeTruthy();
    expect(host.querySelector('app-ba-chart')).toBeTruthy();

    const formulas = host.querySelector('.formulas')!.textContent!.replace(/\s+/g, ' ');
    expect(formulas).toContain('146.23 · √PSD − 1.87');
    expect(formulas).toContain('− (−1.55)');
  });

  it('sorts the pairs table by absolute difference and marks the worst rows', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const rows = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll('#pairs-table tbody tr'));
    expect(rows.map(row => row.querySelector('td')?.textContent?.trim())).toEqual(['3', '1', '2']);
    expect(rows[0].classList.contains('hot')).toBe(true);
    expect(rows[1].classList.contains('hot')).toBe(false);
    // chainage in km with 2 decimals
    expect(rows[0].querySelectorAll('td')[1].textContent?.trim()).toBe('0.25');
  });

  it('selects a segment from a table-row click', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    (host.querySelectorAll('#pairs-table tbody tr')[1] as HTMLElement).click();
    await fixture.whenStable();

    expect(fixture.componentInstance.selectedSegId()).toBe(1);
    expect(host.querySelector('#pairs-table tbody tr.selected')?.textContent)
      .toContain('1');
  });

  it('filters the pairs table by the brushed chainage range', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    fixture.componentInstance.onRange([0.05, 0.3]);
    await fixture.whenStable();

    const rows = (fixture.nativeElement as HTMLElement)
      .querySelectorAll('#pairs-table tbody tr');
    expect(Array.from(rows).map(row => row.querySelector('td')?.textContent?.trim()))
      .toEqual(['3', '2']);
  });

  it('creates a coefficient set with the chosen model and a date-stable default name',
    async () => {
      const createSpy = vi.fn(() => of(CREATED_SET));
      const fixture = createPage(apiStub({
        createCoefficientSet: createSpy as unknown as ApiService['createCoefficientSet'],
      }));
      await fixture.whenStable();
      const host = fixture.nativeElement as HTMLElement;

      click(host, 'Створити набір коефіцієнтів');
      await fixture.whenStable();

      const dialog = host.querySelector('#set-dialog')!;
      const eq3 = dialog.querySelector<HTMLInputElement>('input[value="eq3"]')!;
      expect(eq3.disabled).toBe(false);
      eq3.dispatchEvent(new Event('change'));
      await fixture.whenStable();

      click(dialog.querySelector('.dialog-actions')!, 'Створити');
      await fixture.whenStable();

      expect(createSpy).toHaveBeenCalledWith({
        comparison_id: 3,
        model: 'eq3',
        name: 'eq3_sedan_2026-08-20',
        vehicle_type: 'sedan',
        // Prefilled from the run — never a hand-typed device string
        phone_model: 'samsung SM-S948B',
      });
      expect(host.querySelector('#set-dialog')).toBeFalsy();
      expect(host.querySelector('.success-note')?.textContent)
        .toContain('eq3_sedan_2026-08-20');
    });

  it('offers exactly two phone options and posts the chosen one', async () => {
    const createSpy = vi.fn(() => of(CREATED_SET));
    const fixture = createPage(apiStub({
      createCoefficientSet: createSpy as unknown as ApiService['createCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();

    const dialog = host.querySelector('#set-dialog')!;
    // No free-text phone entry is reachable: the field is a select everywhere
    expect(dialog.querySelector('input[placeholder]')).toBeFalsy();
    const select = dialog.querySelector<HTMLSelectElement>('select')!;
    const options = Array.from(select.options);
    expect(options.map(option => option.textContent?.trim())).toEqual([
      'Точний телефон (samsung SM-S948B)',
      'Будь-який телефон цього типу авто',
    ]);
    expect(select.value).toBe('samsung SM-S948B');

    select.value = '';
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    click(dialog.querySelector('.dialog-actions')!, 'Створити');
    await fixture.whenStable();

    expect(createSpy).toHaveBeenCalledWith(expect.objectContaining({ phone_model: null }));
  });

  it('offers only the «any phone» option for a recording without a device line',
    async () => {
      const fixture = createPage(apiStub({
        getRun: () => of({ ...RUN, phone_model: null }),
      }));
      await fixture.whenStable();
      const host = fixture.nativeElement as HTMLElement;

      click(host, 'Створити набір коефіцієнтів');
      await fixture.whenStable();

      const select = host.querySelector<HTMLSelectElement>('#set-dialog select')!;
      expect(Array.from(select.options).map(option => option.value)).toEqual(['']);
      expect(select.options[0].textContent?.trim())
        .toBe('Будь-який телефон цього типу авто');
    });

  it('shows a failed creation inside the dialog and keeps it open for a retry', async () => {
    const fixture = createPage(apiStub({
      createCoefficientSet: (() => throwError(
        () => ({ error: { detail: 'набір з такою назвою вже існує' } }),
      )) as unknown as ApiService['createCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();
    click(host.querySelector('#set-dialog .dialog-actions')!, 'Створити');
    await fixture.whenStable();

    // The page-level banner sits under the fixed backdrop, so the message must be
    // rendered inside the dialog element itself.
    const dialog = host.querySelector('#set-dialog');
    expect(dialog).toBeTruthy();
    expect(dialog!.querySelector('#set-error')?.textContent)
      .toContain('набір з такою назвою вже існує');
    expect(host.querySelector('.success-note')).toBeFalsy();
    // Retry is possible: the submit button is enabled again
    expect(dialog!.querySelector<HTMLButtonElement>('.dialog-actions .primary')!.disabled)
      .toBe(false);
  });

  it('resets the phone choice and the error when the dialog is reopened', async () => {
    const fixture = createPage(apiStub({
      createCoefficientSet: (() => throwError(
        () => ({ error: { detail: 'набір з такою назвою вже існує' } }),
      )) as unknown as ApiService['createCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();
    const phone = host.querySelector<HTMLSelectElement>('#set-dialog select')!;
    phone.value = '';
    phone.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    click(host.querySelector('#set-dialog .dialog-actions')!, 'Створити');
    await fixture.whenStable();

    click(host.querySelector('#set-dialog .dialog-actions')!, 'Скасувати');
    await fixture.whenStable();
    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();

    // The dialog is destroyed on close, so a reopened one starts from its inputs
    expect(host.querySelector<HTMLSelectElement>('#set-dialog select')!.value)
      .toBe('samsung SM-S948B');
    expect(host.querySelector('#set-error')).toBeFalsy();
  });

  it('blocks the eq3 model and the Eq.3 formula when the fit is degenerate', async () => {
    const degenerate: ChartData = {
      ...CHART, eq3_fit: { A: null, B: null, r2: null, mae: null, n: 3 },
    };
    const fixture = createPage(apiStub({
      getComparison: () => of({
        ...COMPARISON, summary: { ...COMPARISON.summary!, eq3_r2: null },
      }) as unknown as ReturnType<ApiService['getComparison']>,
      getComparisonChartData: () => of(degenerate),
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.querySelector('.formulas .degenerate')?.textContent)
      .toContain('фіт вироджений — недоступно');
    expect(host.querySelector('#gates .chip')?.textContent)
      .toContain('фіт вироджений — недоступно');
    // The scatter keeps its dots but drops the fit line
    expect(host.querySelectorAll('app-scatter-chart circle.dot').length).toBe(3);
    expect(host.querySelectorAll('app-scatter-chart line.fit').length).toBe(0);

    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();
    const eq3 = host.querySelector<HTMLInputElement>('#set-dialog input[value="eq3"]')!;
    expect(eq3.disabled).toBe(true);
    expect(host.querySelector<HTMLInputElement>('#set-dialog input[value="eq6_bias"]')!.checked)
      .toBe(true);
  });

  it('shows the failure banner and no charts for a failed comparison', async () => {
    const fixture = createPage(apiStub({
      getComparison: () => of({
        ...COMPARISON, status: 'failed', summary: null, error: 'еталон не перетинається з раном',
      }) as unknown as ReturnType<ApiService['getComparison']>,
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.querySelector('.error-banner')?.textContent)
      .toContain('еталон не перетинається з раном');
    expect(host.querySelector('app-scatter-chart')).toBeFalsy();
    expect(host.querySelector('#pairs-table')).toBeFalsy();
  });

  it('notes a still-queued comparison instead of empty charts', async () => {
    const fixture = createPage(apiStub({
      getComparison: () => of({
        ...COMPARISON, status: 'queued', summary: null,
      }) as unknown as ReturnType<ApiService['getComparison']>,
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.querySelector('.status-note')?.textContent).toContain('queued');
    expect(host.querySelector('app-profile-chart')).toBeFalsy();
  });

  it('links every fixed figure as PNG and PDF', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const links = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll<HTMLAnchorElement>('.figure-list a'));
    expect(links.length).toBe(6);
    expect(links.map(link => link.getAttribute('href'))).toContain(
      '/api/comparisons/3/artifacts/figures/fig1_scatter_eq3_fit.png');
    expect(links.map(link => link.getAttribute('href'))).toContain(
      '/api/comparisons/3/artifacts/figures/fig2b_bland_altman_corrected.pdf');
  });
});
