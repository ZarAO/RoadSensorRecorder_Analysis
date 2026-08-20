import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'files' },
  {
    path: 'files',
    loadComponent: () => import('./files/files-page').then(m => m.FilesPage),
  },
  {
    path: 'runs',
    loadComponent: () => import('./runs/runs-page').then(m => m.RunsPage),
  },
  {
    path: 'runs/:id',
    loadComponent: () => import('./runs/run-detail').then(m => m.RunDetail),
  },
  {
    path: 'map',
    loadComponent: () => import('./map/global-map-page').then(m => m.GlobalMapPage),
  },
  {
    path: 'calibration',
    loadComponent: () => import('./calibration/calibration-page').then(m => m.CalibrationPage),
  },
  {
    path: 'calibration/comparisons/:id',
    loadComponent: () => import('./calibration/comparison-detail').then(m => m.ComparisonDetail),
  },
  {
    path: 'calibration/references/:id',
    loadComponent: () => import('./calibration/reference-detail').then(m => m.ReferenceDetail),
  },
  {
    path: 'dashboard',
    loadComponent: () => import('./dashboard/dashboard-page').then(m => m.DashboardPage),
  },
];
