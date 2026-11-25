import type { NextConfig } from "next";

const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// NEXT_OUTPUT=export builds a static site (every page is client-rendered and
// talks to the API), so the dashboard can be hosted for free. Security
// headers are then set by the static host (see infrastructure/render/render.yaml).
const isExport = process.env.NEXT_OUTPUT === "export";

const config: NextConfig = {
  output: isExport ? "export" : "standalone",
  trailingSlash: isExport,
  poweredByHeader: false,
  ...(isExport ? {} : { headers }),
};

async function headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Content-Security-Policy",
            value: `default-src 'self'; connect-src 'self' ${api}; img-src 'self' data: ${api} https:; media-src 'self' ${api} https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'`,
          },
        ],
      },
    ];
}

export default config;
