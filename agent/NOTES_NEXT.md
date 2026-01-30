## Next Steps

1. **Phase 8 — UI + manual QA**
   * Run `python manage.py test agent` (schema round-trips, runner/checkpoints, status polling) to lock in the current pipeline.
   * Smoke-test the four scenarios (high review counts, low review counts, no website, rural) so the landing/status/report flows remain resilient and capture runtimes + “one move” takeaways for each.
   * Harden `templates/agent/report_view.html` and `agent/views.py` to cope with sparse data (short supporting moves, empty evidence drawer, missing competitor snapshots).

2. **Phase 9+ — Observability, docs, and reruns**
   * Capture tool/cost metadata per checkpoint, keep `RestaurantReportJob.progress_log` + checkpoints aligned, and add admin/ops notes on how to rerun `run_report_job` when things fail.
   * Document the Stripe checkout/webhook flow, mention the required env vars (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`), and note that Redis/Celery must be running for `run_report_job.delay` to work.
