import type {NextConfig} from 'next';

const securityHeaders = [
  {key: 'X-Frame-Options', value: 'DENY'},
  {key: 'X-Content-Type-Options', value: 'nosniff'},
  {key: 'Referrer-Policy', value: 'no-referrer'},
  {key: 'Cross-Origin-Opener-Policy', value: 'same-origin'},
  {key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()'},
];

const config: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  async headers() {
    return [
      {source: '/:path*', headers: securityHeaders},
      {source: '/api/:path*', headers: [{key: 'Cache-Control', value: 'no-store'}]},
    ];
  },
};

export default config;
