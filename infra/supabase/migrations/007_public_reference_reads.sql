-- =============================================================================
-- 007 — Public-read policies for canonical reference tables
--
-- ``tokens`` and ``news_items`` hold no PII and are shared/canonical data.
-- Allow any authenticated session to read them so the frontend can join
-- without round-tripping through the backend.
-- =============================================================================

create policy "tokens public read" on tokens
  for select using (true);

create policy "news_items public read" on news_items
  for select using (true);
