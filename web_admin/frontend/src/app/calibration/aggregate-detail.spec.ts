import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { AggregateChartData, AggregateOut, CoefficientSetOut, RunOut } from '../api/dto';
import { AggregateDetail } from './aggregate-detail';

const AGGREGATE: AggregateOut = {
  id: 7, reference_id: 1, run_ids: [5, 6, 8], created_at: '2026-08-20T10:05:00Z',
  status: 'done', params: {}, result_dir: 'x',
  summary: {
    n_runs: 3, n_bins: 12, bias: -1.61, bias_ci_low: -1.8, bias_ci_high: -1.42,
    repeatability_sd: 0.34, rho: 0.91, mae_aggregated: 1.12, speed_slope: -0.05,
    stale: false,
  },
  error: null, reference_road: 'M-01 km 12-14',
  run_filenames: ['drive1.csv', 'drive2.csv', 'drive3.csv'],
};

/** Bins deliberately out of chainage order — the table must sort them. */
const CHART: AggregateChartData = {
  profile: [
    { chainage_m: 250, iri_ref: 5.0, mean_iri: 3.4, lo: 3.0, hi: 3.9, n_passes: 3, std_iri: 0.45 },
    { chainage_m: 50, iri_ref: 2.0, mean_iri: 1.9, lo: 1.7, hi: 2.1, n_passes: 3, std_iri: 0.2 },
    { chainage_m: 150, iri_ref: 3.5, mean_iri: 3.6, lo: 3.6, hi: 3.6, n_passes: 1, std_iri: null },
  ],
  bias: {
    bias: -1.61, se: 0.09, ci_low: -1.8, ci_high: -1.42,
    n_bins: 12, n_eff: 9.4, confidence: 0.95,
  },
  repeatability: { sd: 0.34, n_bins_used: 10 },
  speed_effect: {
    slope_iri_per_kmh: -0.05, stderr: 0.01, n_rows: 24, n_bins: 10, speed_spread_kmh: 7.4,
  },
  validation: { rho: 0.91, mae: 1.12 },
};

const RUN: RunOut = {
  id: 5, file_id: 1, filename: 'drive1.csv', created_at: '2026-08-20T10:00:00Z',
  started_at: null, finished_at: null, status: 'done', params: {}, result_dir: 'x',
  summary: {
    segments_total: 3, km_total: 0.3, mean_iri_multi: 5.1, low_speed_count: 0,
    partial_count: 0, events_total: 0, incidents_total: 0, clean_stop: true,
    vehicle_type: 'sedan',
  },
  error: null, phone_model: 'samsung SM-S948B', device_id: null, vehicle_id: null,
};

const CREATED_SET: CoefficientSetOut = {
  id: 12, name: 'eq6_bias_sedan_2026-08-20', model: 'eq6_bias', params: { bias: -1.61 },
  vehicle_type: 'sedan', phone_model: null, device_id: null, vehicle_id: null,
  status: 'draft', comparison_id: null,
  aggregate_comparison_id: 7, stats_snapshot: null, created_at: '2026-08-20T11:00:00Z',
  confirmed_at: null, confirmed_note: null,
};

function apiStub(overrides: Partial<ApiService> = {}): ApiService {
  return {
    getAggregate: () => of(AGGREGATE),
    getAggregateChartData: () => of(CHART),
    getRun: () => of(RUN),
    aggregateArtifactUrl: (id: number, name: string) =>
      `/api/aggregate-comparisons/${id}/artifacts/${name}`,
    createCoefficientSet: () => of(CREATED_SET),
    ...overrides,
  } as Partial<ApiService> as ApiService;
}

function createPage(api: ApiService) {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    imports: [AggregateDetail],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } },
      },
    ],
  });
  return TestBed.createComponent(AggregateDetail);
}

function click(root: ParentNode, label: string): void {
  const button = Array.from(root.querySelectorAll('button'))
    .find(candidate => candidate.textContent?.trim() === label);
  if (!button) throw new Error(`button «${label}» not found`);
  button.click();
}

function text(host: HTMLElement, selector: string): string {
  return (host.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('AggregateDetail', () => {
  it('renders the KPI row with the bias and its confidence interval', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    const cards = Array.from(host.querySelectorAll('.kpi-card'));
    expect(cards.length).toBe(6);
    const bias = cards.find(card => card.textContent?.includes('Зсув'))!;
    const biasText = bias.textContent!.replace(/\s+/g, ' ');
    expect(biasText).toContain('−1.61');
    expect(biasText).toContain('[−1.80; −1.42]');
    expect(text(host, '.cards')).toContain('3');
    expect(text(host, '.cards')).toContain('0.91');
  });

  it('renders «—» instead of null for the missing repeatability and rho', async () => {
    const fixture = createPage(apiStub({
      getAggregate: () => of({
        ...AGGREGATE,
        summary: {
          ...AGGREGATE.summary!, repeatability_sd: null, rho: null,
          mae_aggregated: null, bias: null, bias_ci_low: null, bias_ci_high: null,
        },
      }) as unknown as ReturnType<ApiService['getAggregate']>,
      getAggregateChartData: () => of({
        ...CHART, repeatability: { sd: null, n_bins_used: 0 }, speed_effect: null,
      }),
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    const cards = Array.from(host.querySelectorAll('.kpi-card'));
    const sigma = cards.find(card => card.textContent?.includes('повторюваність'))!;
    expect(sigma.querySelector('.num')?.textContent?.trim()).toBe('—');
    const bias = cards.find(card => card.textContent?.includes('Зсув'))!;
    expect(bias.textContent).not.toContain('null');
    expect(host.textContent).not.toContain('null');
  });

  it('marks a stale aggregate whose pass was deleted', async () => {
    const fixture = createPage(apiStub({
      getAggregate: () => of({
        ...AGGREGATE, summary: { ...AGGREGATE.summary!, stale: true },
      }) as unknown as ReturnType<ApiService['getAggregate']>,
    }));
    await fixture.whenStable();

    const chip = (fixture.nativeElement as HTMLElement).querySelector('.chip.stale');
    expect(chip).toBeTruthy();
    expect(chip!.textContent).toContain('stale');
  });

  it('draws the pooled profile as a band plus the reference and mean-pass lines', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    const chart = host.querySelector('app-multi-line-chart')!;
    expect(chart).toBeTruthy();
    expect(chart.querySelectorAll('path.band').length).toBe(1);
    expect(chart.querySelectorAll('path.line').length).toBe(2);
    const legend = chart.querySelector('.legend')!.textContent!.replace(/\s+/g, ' ');
    expect(legend).toContain('Еталон');
    expect(legend).toContain('Смартфон (середнє проїздів)');
  });

  it('reports the speed effect with its stderr and sample size', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const card = text(fixture.nativeElement as HTMLElement, '#speed-effect');
    expect(card).toContain('−0.050');
    expect(card).toContain('±0.010');
    expect(card).toContain('24');
    expect(card).toContain('7.4');
  });

  it('explains a non-estimated speed effect instead of showing a slope', async () => {
    const fixture = createPage(apiStub({
      getAggregateChartData: () => of({ ...CHART, speed_effect: null }),
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(text(host, '#speed-effect')).toContain('Швидкісний ефект не оцінено');
    expect(host.querySelector('#speed-effect .muted')).toBeTruthy();
  });

  it('sorts the bins table by chainage and shows «—» for a single-pass std', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();

    const rows = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll('#bins-table tbody tr'));
    expect(rows.map(row => row.querySelector('td')?.textContent?.trim()))
      .toEqual(['0.050', '0.150', '0.250']);
    const cells = Array.from(rows[1].querySelectorAll('td')).map(cell => cell.textContent?.trim());
    // chainage, iri_ref, mean, std, n_passes, diff
    expect(cells).toEqual(['0.150', '3.50', '3.60', '—', '1', '+0.10']);
  });

  it('creates an eq6_bias set from the aggregate, never eq3', async () => {
    const createSpy = vi.fn(() => of(CREATED_SET));
    const fixture = createPage(apiStub({
      createCoefficientSet: createSpy as unknown as ApiService['createCoefficientSet'],
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    click(host, 'Створити набір коефіцієнтів');
    await fixture.whenStable();

    const dialog = host.querySelector('#set-dialog')!;
    expect(dialog.querySelector<HTMLInputElement>('input[value="eq3"]')!.disabled).toBe(true);
    expect(dialog.querySelector<HTMLInputElement>('input[value="eq6_bias"]')!.checked).toBe(true);

    // The phone key is prefilled from the first pass — no free-text entry here either
    expect(dialog.querySelector('input[placeholder]')).toBeFalsy();
    const select = dialog.querySelector<HTMLSelectElement>('select')!;
    expect(Array.from(select.options).map(option => option.textContent?.trim())).toEqual([
      'Точний телефон (samsung SM-S948B)',
      'Будь-який телефон цього типу авто',
    ]);

    click(dialog.querySelector('.dialog-actions')!, 'Створити');
    await fixture.whenStable();

    expect(createSpy).toHaveBeenCalledWith({
      aggregate_comparison_id: 7,
      model: 'eq6_bias',
      name: 'eq6_bias_sedan_2026-08-20',
      vehicle_type: 'sedan',
      phone_model: 'samsung SM-S948B',
      device_id: null, vehicle_id: null,
    });
    expect(host.querySelector('#set-dialog')).toBeFalsy();
    expect(host.querySelector('.success-note')?.textContent)
      .toContain('eq6_bias_sedan_2026-08-20');
  });

  it('links the aggregate figures, dropping the speed figure when there is no slope', async () => {
    const fixture = createPage(apiStub());
    await fixture.whenStable();
    const links = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll<HTMLAnchorElement>('.figure-list a'))
      .map(link => link.getAttribute('href'));
    expect(links).toContain('/api/aggregate-comparisons/7/artifacts/figures/fig_agg_profile.png');
    expect(links).toContain('/api/aggregate-comparisons/7/artifacts/figures/fig_agg_speed.pdf');

    const flat = createPage(apiStub({
      getAggregateChartData: () => of({ ...CHART, speed_effect: null }),
    }));
    await flat.whenStable();
    const flatLinks = Array.from((flat.nativeElement as HTMLElement)
      .querySelectorAll<HTMLAnchorElement>('.figure-list a'))
      .map(link => link.getAttribute('href'));
    expect(flatLinks.length).toBe(2);
    expect(flatLinks.join(' ')).not.toContain('fig_agg_speed');
  });

  it('shows the failure reason and no charts for a failed aggregate', async () => {
    const fixture = createPage(apiStub({
      getAggregate: () => of({
        ...AGGREGATE, status: 'failed', summary: null,
        error: 'ран #6: замало зіставлених пар (3)',
      }) as unknown as ReturnType<ApiService['getAggregate']>,
    }));
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.querySelector('.error-banner')?.textContent).toContain('замало зіставлених пар');
    expect(host.querySelector('app-multi-line-chart')).toBeFalsy();
    expect(host.querySelector('#bins-table')).toBeFalsy();
  });
});
