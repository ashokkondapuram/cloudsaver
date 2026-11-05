import {defineConfig} from '@playwright/test';

const baseURL = process.env.CLOUDSAVER_DASHBOARD_URL || 'http://127.0.0.1:3000';
const address = new URL(baseURL);
if (!['127.0.0.1', 'localhost'].includes(address.hostname) || address.protocol !== 'http:') {
  throw new Error('Browser fixtures require a loopback HTTP test server.');
}

/** Enterprise UI / control-plane / FinOps ladder specs. */
export const enterpriseUiTestMatch = [
  '**/enterprise-ui*.spec.ts',
  '**/control-plane-*.spec.ts',
  '**/financial-scenario-absorption.spec.ts',
  '**/declared-workloads-if-match.spec.ts',
  '**/commitment-expiry-badges.spec.ts',
];

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    launchOptions: process.env.CLOUDSAVER_BROWSER_EXECUTABLE
      ? {executablePath: process.env.CLOUDSAVER_BROWSER_EXECUTABLE}
      : process.env.CLOUDSAVER_BROWSER_CHANNEL
        ? {channel: process.env.CLOUDSAVER_BROWSER_CHANNEL as 'msedge' | 'chrome'}
        : undefined,
    screenshot: 'only-on-failure',
  },
  projects: [
    {name: 'enterprise-ui', testMatch: enterpriseUiTestMatch},
    {name: 'dashboard', testIgnore: enterpriseUiTestMatch},
  ],
});
