from celery import shared_task
from django.utils import timezone

from gastronet.management.commands.seed_places import Command as SeedPlacesCommand
from gastronet.management.commands.fetch_reviews import Command as FetchReviewsCommand
from gastronet.management.commands.schedule_refresh import Command as ScheduleRefreshCommand
from gastronet.models import CrawlLog
from gastronet.openai_batches import services as batch_services


@shared_task(bind=True, max_retries=3)
def seed_places(self, query="restaurants in Seattle, WA", limit=500):
    SeedPlacesCommand().handle(query=query, limit=limit)
    return "seed complete"


@shared_task(bind=True, max_retries=3)
def fetch_reviews(self, batch=60, per_place_limit=10):
    FetchReviewsCommand().handle(batch=batch, per_place_limit=per_place_limit)
    return "reviews fetched"


@shared_task(bind=True, max_retries=3)
def schedule_refresh(self, min_days=3.0, max_days=90.0, alpha=0.8, limit=5000):
    ScheduleRefreshCommand().handle(
        min_days=min_days, max_days=max_days, alpha=alpha, limit=limit
    )
    return "refresh schedule updated"


@shared_task(bind=True)
def heartbeat(self):
    CrawlLog.objects.create(
        task="heartbeat",
        scope="system",
        success_count=1,
        notes=f"beat @ {timezone.now().isoformat()}",
    )
    return "alive"


@shared_task(bind=True, queue="render", max_retries=2)
def render_menu_page(self, url):
    """
    Run Playwright headless render to return HTML of a page.
    Heavy task → runs only on 'render' queue.
    """
    from playwright.async_api import async_playwright
    async def _render():
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, timeout=25000)
                await asyncio.sleep(2.5)
                html = await page.content()
                await browser.close()
                return html
        except Exception as e:
            return ""

    try:
        return asyncio.run(_render())
    except Exception:
        return ""


@shared_task(bind=True, max_retries=3)
def openai_batch_submit_task(self, job_type, params=None, limit=5000, batch_size=5000):
    jobs = batch_services.submit_batches(job_type, params or {}, limit, batch_size)
    return [job.batch_id for job in jobs]


@shared_task(bind=True)
def openai_batch_poll_active(self, batch_ids=None):
    updated = batch_services.poll_active_jobs(batch_ids=batch_ids)
    return [job.batch_id for job in updated]


@shared_task(bind=True)
def openai_batch_apply_job(self, job_id):
    return batch_services.apply_job(job_id)


@shared_task(bind=True)
def openai_batch_apply_ready(self, limit=None, job_type=None):
    return batch_services.apply_ready_jobs(limit=limit, job_type=job_type)
