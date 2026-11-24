"""Real-browser regression check for the product catalogue (run explicitly in CI)."""
from decimal import Decimal

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Product


class ProductWorkspaceBrowserTests(StaticLiveServerTestCase):
    def test_catalogue_layout_navigation_and_controls(self):
        from playwright.sync_api import sync_playwright

        user = User.objects.create_superuser(
            username="workspace-browser", email="workspace@example.test", password="test-password"
        )
        self.client.force_login(user)
        for index in range(6):
            Product.objects.create(
                sku=f"BROWSER-{index}",
                name=("Long product name with multiple words and inventory details " if index == 0 else "Lash product ") + str(index),
                selling_price=Decimal("1200.00"), cost_price=Decimal("500.00"),
                on_hand=Decimal("0") if index == 0 else Decimal("8"),
                reorder_level=Decimal("5"),
            )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                context.add_cookies([{
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                    "url": self.live_server_url,
                }])
                # Check local CSS and controls without depending on remote font/CDN uptime.
                context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.live_server_url + "/") else route.abort())
                page = context.new_page()
                page.goto(self.live_server_url + reverse("admin:catalog_product_changelist"), wait_until="load")
                page.locator("#product-grid").wait_for()
                self.assertEqual(page.locator(".product-card").count(), 6)
                self.assertEqual(page.locator("#product-grid").evaluate("(el) => getComputedStyle(el).display"), "grid")
                for width in (320, 375, 390, 600, 768, 1024, 1440, 1920):
                    with self.subTest(width=width):
                        page.set_viewport_size({"width": width, "height": 900})
                        page.wait_for_function("document.documentElement.clientWidth === " + str(width))
                        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Document overflows at {width}px")
                        self.assertTrue(page.locator(".product-card").evaluate_all("(cards) => cards.every(c => { const r = c.getBoundingClientRect(); return r.left >= -1 && r.right <= innerWidth + 1; })"), f"Card overflows at {width}px")
                        self.assertTrue(page.get_by_role("link", name="Add product").is_visible())
                        if width <= 860:
                            menu = page.locator("#product-menu-toggle")
                            menu.wait_for(state="visible")
                            if menu.get_attribute("aria-expanded") == "true":
                                menu.click()
                            menu.click()
                            self.assertTrue(page.locator("#product-nav").get_by_role("link", name="Checkout").is_visible())
                            menu.click()
                            self.assertFalse(page.locator("#product-nav").is_visible())
                        else:
                            page.locator("#product-menu-toggle").wait_for(state="hidden")
                            self.assertTrue(page.locator("#product-nav").get_by_role("link", name="Checkout").is_visible())
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#theme-toggle").click()
                self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
                page.locator("#product-select-all").check()
                self.assertEqual(page.locator("#product-selection").inner_text(), "6 selected")
                page.locator("#product-select-all").uncheck()
                page.locator("#product-search input[type=search]").fill("BROWSER-0")
                page.locator("#product-search button").click()
                page.wait_for_url("**/*q=BROWSER-0*")
                self.assertEqual(page.locator(".product-card").count(), 1)
                self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
            finally:
                browser.close()
