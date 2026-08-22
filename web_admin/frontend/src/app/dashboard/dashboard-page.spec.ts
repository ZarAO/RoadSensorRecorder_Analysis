import { By } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ApiService } from '../api/api.service';
import { DashboardOut, IriHistogramBin, VehicleTypeStats } from '../api/dto';
import { CountUp } from '../shared/count-up';
import { DashboardPage } from './dashboard-page';

const HIST: IriHistogramBin[] = [{ bin_start: 0, bin_end: 1, count: 2 }];

const UNKNOWN_STATS: VehicleTypeStats = {
  files_total: 3, runs_done: 3, km_total: 10.5, low_speed_total: 2,
  mean_iri_multi: null, iri_histogram: HIST,
};

const DASHBOARD: DashboardOut = {
  files_total: 3,
  runs_done: 3,
  km_total: 10.5,
  low_speed_total: 2,
  iri_histogram: HIST,
  worst_segments: [],
  by_vehicle_type: {
    van: {
      files_total: 1, runs_done: 1, km_total: 4.2, low_speed_total: 1,
      mean_iri_multi: 3.1, iri_histogram: [{ bin_start: 0, bin_end: 1, count: 1 }],
    },
    sedan: {
      files_total: 2, runs_done: 2, km_total: 6.3, low_speed_total: 1,
      mean_iri_multi: 2.5, iri_histogram: [{ bin_start: 0, bin_end: 1, count: 1 }],
    },
  },
};

describe('DashboardPage', () => {
  function setup(data: DashboardOut = DASHBOARD) {
    TestBed.resetTestingModule();
    const api = { getDashboard: () => of(data) } as unknown as ApiService;
    TestBed.configureTestingModule({
      imports: [DashboardPage],
      providers: [provideRouter([]), { provide: ApiService, useValue: api }],
    });
    return TestBed.createComponent(DashboardPage);
  }

  function kmValue(fixture: ReturnType<typeof setup>): number {
    return (fixture.debugElement.queryAll(By.directive(CountUp))[0]
      .componentInstance as CountUp).value();
  }

  it('shows the global km KPI by default («Всі») and swaps it on chip click', async () => {
    const fixture = setup();
    await fixture.whenStable();
    expect(kmValue(fixture)).toBe(10.5); // «Всі» = existing global field, unchanged

    const host = fixture.nativeElement as HTMLElement;
    const vanChip = Array.from(host.querySelectorAll('.type-chips button'))
      .find(b => b.textContent?.trim() === 'van') as HTMLButtonElement;
    expect(vanChip).toBeTruthy();
    vanChip.click();
    await fixture.whenStable();

    expect(kmValue(fixture)).toBe(4.2); // the fixture's per-type value for 'van'
  });

  it('shows one chip per vehicle type, but hides the row when the only type is «невідомо»', async () => {
    const withTypes = setup(DASHBOARD);
    await withTypes.whenStable();
    expect((withTypes.nativeElement as HTMLElement).querySelector('.type-chips')).toBeTruthy();

    const unknownOnly = setup({ ...DASHBOARD, by_vehicle_type: { 'невідомо': UNKNOWN_STATS } });
    await unknownOnly.whenStable();
    expect((unknownOnly.nativeElement as HTMLElement).querySelector('.type-chips')).toBeFalsy();
  });
});
