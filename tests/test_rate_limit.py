"""v0.45.6 unit tests for lib.rate_limit."""

import os
import sys
import time

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests


class DomainParseTests(TestCase):
    def test_url_extracts_netloc(self):
        from lib.rate_limit import _domain_of
        self.assertEqual(
            _domain_of("https://www.sciencedirect.com/article/x"),
            "www.sciencedirect.com",
        )

    def test_bare_domain_lowercased(self):
        from lib.rate_limit import _domain_of
        self.assertEqual(_domain_of("ScienceDirect.COM"),
                         "sciencedirect.com")

    def test_url_with_port(self):
        from lib.rate_limit import _domain_of
        self.assertEqual(_domain_of("http://example.com:8080/x"),
                         "example.com:8080")


class WaitTests(TestCase):
    def test_first_call_does_not_block(self):
        with isolated_cache():
            from lib.rate_limit import wait
            t0 = time.monotonic()
            wait("example.com", delay_seconds=0.5)
            elapsed = time.monotonic() - t0
            # First call: no marker yet → must not block
            self.assertLess(elapsed, 0.3)

    def test_marker_file_created_after_wait(self):
        with isolated_cache():
            from lib.cache import cache_root
            from lib.rate_limit import wait
            wait("example.com", delay_seconds=0.0)
            marker = cache_root() / "rate_limit" / "example.com.last"
            self.assertTrue(marker.exists())

    def test_second_call_blocks_until_delay_elapsed(self):
        with isolated_cache():
            from lib.rate_limit import wait
            wait("example.com", delay_seconds=0.0)  # set marker
            t0 = time.monotonic()
            wait("example.com", delay_seconds=0.4)
            elapsed = time.monotonic() - t0
            # Should have blocked roughly 0.4s
            self.assertGreater(elapsed, 0.3)
            self.assertLess(elapsed, 0.8)

    def test_separate_domains_do_not_interfere(self):
        with isolated_cache():
            from lib.rate_limit import wait
            wait("a.com", delay_seconds=0.0)
            t0 = time.monotonic()
            wait("b.com", delay_seconds=0.5)
            # Different domain → fresh marker → no block
            self.assertLess(time.monotonic() - t0, 0.3)

    def test_url_and_bare_domain_share_marker(self):
        with isolated_cache():
            from lib.rate_limit import wait
            wait("https://x.com/path", delay_seconds=0.0)
            t0 = time.monotonic()
            # Same domain via bare form → must block
            wait("x.com", delay_seconds=0.4)
            self.assertGreater(time.monotonic() - t0, 0.3)

    def test_env_override(self):
        with isolated_cache():
            from lib.rate_limit import wait
            wait("env.com", delay_seconds=0.0)
            os.environ["COSCIENTIST_PUBLISHER_DELAY"] = "0.4"
            try:
                t0 = time.monotonic()
                wait("env.com")  # no explicit delay → use env
                self.assertGreater(time.monotonic() - t0, 0.3)
            finally:
                os.environ.pop("COSCIENTIST_PUBLISHER_DELAY", None)

    def test_path_unsafe_chars_in_domain_sanitised(self):
        with isolated_cache():
            from lib.cache import cache_root
            from lib.rate_limit import wait
            wait("https://host:8080/x", delay_seconds=0.0)
            # Marker file uses sanitised name (no `/` or `:`)
            files = list((cache_root() / "rate_limit").iterdir())
            self.assertEqual(len(files), 1)
            self.assertNotIn(":", files[0].name.replace(".last", ""))
            self.assertNotIn("/", files[0].name)


if __name__ == "__main__":
    sys.exit(run_tests(DomainParseTests, WaitTests))
