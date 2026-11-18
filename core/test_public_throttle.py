from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.models import PublicRateLimitBucket
from core.public_throttle import public_rate_limit


@public_rate_limit("unit-test", limits={"POST": (2, 60)})
def _limited_view(request):
    return HttpResponse("ok")


class PublicThrottleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post(self, address):
        request = self.factory.post("/test/", data={})
        request.META["REMOTE_ADDR"] = address
        return _limited_view(request)

    def test_request_limit_returns_429_and_retry_after(self):
        self.assertEqual(self._post("203.0.113.10").status_code, 200)
        self.assertEqual(self._post("203.0.113.10").status_code, 200)
        response = self._post("203.0.113.10")
        self.assertEqual(response.status_code, 429)
        self.assertTrue(int(response["Retry-After"]) > 0)
        self.assertEqual(PublicRateLimitBucket.objects.count(), 1)

    def test_buckets_are_separated_by_ip_and_do_not_store_raw_address(self):
        self._post("203.0.113.11")
        self._post("203.0.113.12")
        self.assertEqual(PublicRateLimitBucket.objects.count(), 2)
        self.assertNotIn("203.0.113.11", PublicRateLimitBucket.objects.values_list("key_hash", flat=True))

    def test_unconfigured_methods_are_not_counted(self):
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "203.0.113.13"
        self.assertEqual(_limited_view(request).status_code, 200)
        self.assertEqual(PublicRateLimitBucket.objects.count(), 0)
