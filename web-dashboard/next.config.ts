import type {NextConfig} from 'next';
const config:NextConfig={output:'standalone',poweredByHeader:false,async redirects(){return [{source:'/admin/:path*',destination:'/',permanent:false}];}};
export default config;
