// Sentry server init — runs in Node.js for SSR + route handlers.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN ?? process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_ENV ?? "development",
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
  });
}
