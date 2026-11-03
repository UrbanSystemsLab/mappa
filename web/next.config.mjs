// Built as plain files (output: 'export') that the FastAPI server serves, so
// the site stays one Cloud Run service. During `npm run dev` the API calls go
// to the local server started by scripts/run_local.sh.
const API = process.env.MAPPA_API || 'http://127.0.0.1:8765';

/** @type {import('next').NextConfig} */
const config = {
  output: 'export',
  trailingSlash: true,
  skipTrailingSlashRedirect: true, // never on /api/... calls
  images: { unoptimized: true },
  ...(process.env.NODE_ENV === 'development' && {
    async rewrites() {
      return [{ source: '/api/:path*', destination: `${API}/api/:path*` }];
    },
  }),
};

export default config;
