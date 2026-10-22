import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir:'./e2e',
  workers:1,
  reporter:'list',
  use:{
    baseURL:process.env.CLOUDSAVER_DASHBOARD_URL||'http://127.0.0.1:3000',
    launchOptions:process.env.CLOUDSAVER_BROWSER_EXECUTABLE?{executablePath:process.env.CLOUDSAVER_BROWSER_EXECUTABLE}:undefined,
    screenshot:'only-on-failure',
  },
});
