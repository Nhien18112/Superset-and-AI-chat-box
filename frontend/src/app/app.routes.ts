import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./features/landing/landing.component').then(m => m.LandingComponent) },
  { path: 'login', loadComponent: () => import('./features/login/login.component').then(m => m.LoginComponent) },
  { path: 'dashboard', loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent) },
  { path: '**', redirectTo: '' }
];
