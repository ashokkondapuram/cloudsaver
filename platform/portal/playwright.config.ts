import {defineConfig} from '@playwright/test';
const baseURL=process.env.CLOUDSAVER_PORTAL_URL||'http://127.0.0.1:3199';
const address=new URL(baseURL);
if(!['127.0.0.1','localhost'].includes(address.hostname)||address.protocol!=='http:')throw new Error('Portal browser fixtures require a loopback HTTP test server.');
export default defineConfig({
  testDir:'./e2e',workers:1,reporter:'list',
  use:{baseURL,launchOptions:process.env.CLOUDSAVER_BROWSER_EXECUTABLE?{executablePath:process.env.CLOUDSAVER_BROWSER_EXECUTABLE}:undefined,screenshot:'only-on-failure'},
  webServer:{command:`node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port ${address.port||80}`,url:baseURL,reuseExistingServer:false,timeout:45000,
    env:{PLATFORM_ENVIRONMENT:'development',PORTAL_PUBLIC_URL:baseURL,NEXT_TELEMETRY_DISABLED:'1'}},
});
