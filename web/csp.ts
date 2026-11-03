// Content Security Policy for the built page. GitHub Pages cannot set headers, so the policy
// is a <meta> tag that the build writes before any script. `default-src` does not cover
// base-uri, object-src or form-action, so they are listed. A meta tag cannot set
// frame-ancestors, so the page cannot stop itself being framed. It has no sensitive action.

export const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'none'",
  "object-src 'none'",
  "form-action 'none'",
].join("; ");
