"""Read-only smoke checks for LashPro staging.

Install ``qa/requirements.txt`` and Playwright's Chromium browser first. Set
``LASHPRO_DEMO_PASSWORD`` before running. The optional owner test also needs
``LASHPRO_OWNER_USERNAME`` and ``LASHPRO_OWNER_PASSWORD``. These checks
authenticate and issue GET requests only; they do not create sales,
enrollments, payments, or refunds. No passwords are stored in this file.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest
import truststore

truststore.inject_into_ssl()

import requests

BASE_URL = os.getenv(
    "LASHPRO_STAGE_URL", "https://lashpro-pos-alpha.onrender.com"
).rstrip("/")
PASSWORD = os.getenv("LASHPRO_DEMO_PASSWORD", "")
OWNER_USERNAME = os.getenv("LASHPRO_OWNER_USERNAME", "")
OWNER_PASSWORD = os.getenv("LASHPRO_OWNER_PASSWORD", "")
ROLE_USERS = {
    "manager": "demo_manager",
    "cashier": "demo_cashier",
    "technician": "demo_technician_1",
    "trainer": "demo_trainer",
}

if not PASSWORD:
    pytest.skip("Set LASHPRO_DEMO_PASSWORD to run staging checks", allow_module_level=True)


def _csrf_token(html: str) -> str:
    match = re.search(
        r'name=["\']csrfmiddlewaretoken["\'][^>]*value=["\']([^"\']+)', html
    )
    if not match:
        match = re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']csrfmiddlewaretoken["\']',
            html,
        )
    assert match, "CSRF token field was not rendered"
    return match.group(1)


def _login(username: str) -> requests.Session:
    client = requests.Session()
    login_page = client.get(
        f"{BASE_URL}/accounts/login/?next=/", timeout=30
    )
    assert login_page.status_code == 200, "Login page did not load"
    token = _csrf_token(login_page.text)
    response = client.post(
        login_page.url,
        data={
            "username": username,
            "password": PASSWORD,
            "csrfmiddlewaretoken": token,
        },
        headers={"Referer": login_page.url},
        allow_redirects=True,
        timeout=30,
    )
    assert "sessionid" in client.cookies, "Login did not create a session"
    assert urlparse(response.url).path != "/accounts/login/", "Login was rejected"
    return client


@pytest.fixture(scope="session")
def role_sessions():
    clients: dict[str, requests.Session] = {}
    try:
        for role, username in ROLE_USERS.items():
            clients[role] = _login(username)
        yield clients
    finally:
        logout_pages = {
            "manager": "/sales/checkout/",
            "cashier": "/sales/checkout/",
            "technician": "/sales/services/",
            "trainer": "/training/",
        }
        for role, client in clients.items():
            try:
                page = _get(client, logout_pages[role])
                if page.status_code == 200:
                    client.post(
                        f"{BASE_URL}/accounts/logout/",
                        data={"csrfmiddlewaretoken": _csrf_token(page.text)},
                        headers={"Referer": page.url},
                        allow_redirects=True,
                        timeout=30,
                    )
            except Exception:
                pass
            client.close()


def _get(client: requests.Session, path: str) -> requests.Response:
    return client.get(f"{BASE_URL}{path}", timeout=30)


def test_health_and_unauthenticated_redirect():
    response = requests.get(f"{BASE_URL}/healthz", timeout=30)
    assert response.status_code == 200
    assert response.text.strip() == "ok"
    protected = requests.get(
        f"{BASE_URL}/sales/checkout/", allow_redirects=False, timeout=30
    )
    assert protected.status_code in (301, 302, 303, 307, 308)
    assert "/accounts/login/" in protected.headers.get("Location", "")


def test_sign_out_ends_access():
    client = _login(ROLE_USERS["manager"])
    page = _get(client, "/sales/checkout/")
    assert page.status_code == 200
    logout = client.post(
        f"{BASE_URL}/accounts/logout/",
        data={"csrfmiddlewaretoken": _csrf_token(page.text)},
        headers={"Referer": page.url},
        allow_redirects=True,
        timeout=30,
    )
    assert logout.status_code == 200
    protected = client.get(
        f"{BASE_URL}/sales/checkout/", allow_redirects=False, timeout=30
    )
    assert protected.status_code in (301, 302, 303, 307, 308)
    assert "/accounts/login/" in protected.headers.get("Location", "")


def test_default_role_landing_pages(role_sessions):
    expected = {
        "manager": ("/sales/checkout/", 200),
        "cashier": ("/sales/checkout/", 200),
        "technician": ("/sales/services/", 200),
        "trainer": ("/training/", 200),
    }
    for role, (expected_path, expected_status) in expected.items():
        response = _get(role_sessions[role], "/")
        assert urlparse(response.url).path == expected_path, f"Unexpected {role} landing page"
        assert response.status_code == expected_status, f"{role} landing page is not usable"


def test_manager_can_open_read_only_management_surfaces(role_sessions):
    manager = role_sessions["manager"]
    for path in (
        "/reports/",
        "/payments/reconciliation/",
        "/sales/refunds/",
        "/training/manage/",
    ):
        assert _get(manager, path).status_code == 200, f"Manager surface failed: {path}"


def test_manager_training_dashboard_loads(role_sessions):
    assert _get(role_sessions["manager"], "/training/").status_code == 200


def test_cashier_cannot_open_manager_surfaces_or_approve_refunds(role_sessions):
    cashier = role_sessions["cashier"]
    for path in ("/reports/", "/payments/reconciliation/", "/training/manage/"):
        assert _get(cashier, path).status_code == 403, f"Cashier was not blocked: {path}"
    refunds = _get(cashier, "/sales/refunds/")
    assert refunds.status_code == 200
    assert not re.search(
        r"<button[^>]*>\s*(Approve|Issue refund)", refunds.text, re.IGNORECASE
    ), "Cashier was shown a refund approval control"


def test_technician_cannot_use_cashier_checkout(role_sessions):
    technician = role_sessions["technician"]
    assert _get(technician, "/sales/checkout/").status_code == 403
    assert _get(technician, "/sales/services/").status_code == 200
    assert _get(technician, "/reports/").status_code == 403


def test_trainer_scope_and_student_data_visibility(role_sessions):
    manager = role_sessions["manager"]
    trainer = role_sessions["trainer"]
    manager_page = _get(manager, "/training/manage/")
    trainer_page = _get(trainer, "/training/")
    assert manager_page.status_code == 200
    assert trainer_page.status_code == 200
    assert _get(trainer, "/training/manage/").status_code == 403

    all_ids = set(
        re.findall(r'href=["\']/training/manage/cohorts/(\d+)/["\']', manager_page.text)
    )
    assigned_ids = set(
        re.findall(r'href=["\']/training/cohorts/(\d+)/["\']', trainer_page.text)
    )
    assert assigned_ids <= all_ids, "Trainer saw a cohort outside the manager roster"

    for cohort_id in all_ids - assigned_ids:
        assert _get(trainer, f"/training/cohorts/{cohort_id}/").status_code == 403

    for cohort_id in assigned_ids:
        detail = _get(trainer, f"/training/cohorts/{cohort_id}/")
        assert detail.status_code == 200
        assert not re.search(r"phone|tuition|KSh", detail.text, re.IGNORECASE), (
            "Trainer cohort page exposed student phone or tuition fields"
        )


def test_trainer_dashboard_does_not_show_student_contact_or_tuition(role_sessions):
    trainer_page = _get(role_sessions["trainer"], "/training/")
    assert trainer_page.status_code == 200
    assert not re.search(r"phone|tuition|KSh", trainer_page.text, re.IGNORECASE)


def test_password_reset_and_change_forms_are_reachable(role_sessions):
    manager = role_sessions["manager"]
    assert _get(manager, "/accounts/password-change/").status_code == 200
    assert requests.get(f"{BASE_URL}/accounts/password-reset/", timeout=30).status_code == 200


@pytest.mark.skipif(
    not OWNER_USERNAME or not OWNER_PASSWORD,
    reason="Owner credentials were not supplied",
)
def test_owner_can_open_read_only_admin_surface():
    client = requests.Session()
    login_url = f"{BASE_URL}/admin/login/?next=/admin/"
    login_page = client.get(login_url, timeout=30)
    assert login_page.status_code == 200, "Admin login page did not load"
    response = client.post(
        login_page.url,
        data={
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
            "csrfmiddlewaretoken": _csrf_token(login_page.text),
        },
        headers={"Referer": login_page.url},
        allow_redirects=True,
        timeout=30,
    )
    assert "sessionid" in client.cookies, "Owner login did not create a session"
    assert urlparse(response.url).path == "/admin/", "Owner could not open the admin surface"
    assert response.status_code == 200


@pytest.mark.parametrize("viewport", [(1440, 900), (390, 844)])
def test_manager_checkout_login_with_playwright(viewport):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        page.goto(f"{BASE_URL}/accounts/login/?next=/", wait_until="domcontentloaded")
        page.get_by_label("Username", exact=True).fill(ROLE_USERS["manager"])
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/sales/checkout/", timeout=30000)
        assert page.get_by_role("heading", name="New checkout").is_visible()
        assert page.get_by_role("link", name="Reports").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
