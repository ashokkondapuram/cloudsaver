import {defineConfig} from '@playwright/test';

const baseURL=process.env.CLOUDSAVER_DASHBOARD_URL||'http://127.0.0.1:3000';
const address=new URL(baseURL);
if(!['127.0.0.1','localhost'].includes(address.hostname)||address.protocol!=='http:')throw new Error('Browser fixtures require a loopback HTTP test server.');

export default defineConfig({
  testDir:'./e2e',
  workers:1,
  reporter:'list',
  use:{
    baseURL,
    launchOptions:process.env.CLOUDSAVER_BROWSER_EXECUTABLE?{executablePath:process.env.CLOUDSAVER_BROWSER_EXECUTABLE}:undefined,
    screenshot:'only-on-failure',
  },
});
