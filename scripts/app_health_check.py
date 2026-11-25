#!/usr/bin/env python3
"""
Check if web applications are up by looking at the HTTP status code.

An app is UP when it answers with one of the expected status codes
(any 2xx or 3xx by default). It is DOWN when it answers with anything
else, times out, or doesn't accept the connection at all.

    ./app_health_check.py http://localhost:4499
    ./app_health_check.py https://wisecow.local --insecure
    ./app_health_check.py https://example.com/health --expect 200 --interval 30 --log health.log

Exits with 0 when every URL is up and 1 otherwise.
"""

import argparse
import http.client
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

DEFAULT_CODES = frozenset(range(200, 400))

log = logging.getLogger("app_health_check")


@dataclass
class Result:
    url: str
    up: bool
    status: Optional[int]
    elapsed_ms: int
    error: str = ""

    def __str__(self):
        state = "UP" if self.up else "DOWN"
        detail = f"HTTP {self.status}" if self.status is not None else self.error
        return f"{state:<4}  {self.url}  ({detail}, {self.elapsed_ms} ms)"


def parse_codes(value):
    """Turn '200,204,300-399' into a set of ints."""
    codes = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            codes.update(range(int(low), int(high) + 1))
        else:
            codes.add(int(part))
    if not codes:
        raise ValueError("no status codes")
    return codes


def check(url, timeout=5.0, expected=DEFAULT_CODES, verify_tls=True):
    context = None
    if not verify_tls:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    request = urllib.request.Request(url, headers={"User-Agent": "app-health-check"})
    status, error = None, ""
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
        e.close()
    except urllib.error.URLError as e:
        error = str(e.reason)
    except (http.client.HTTPException, OSError) as e:
        error = str(e) or type(e).__name__
    elapsed = int((time.monotonic() - start) * 1000)

    return Result(url, status in expected, status, elapsed, error)


def check_with_retries(url, retries=1, delay=2.0, **kwargs):
    result = check(url, **kwargs)
    for _ in range(retries):
        if result.up:
            break
        time.sleep(delay)
        result = check(url, **kwargs)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check if web applications are up based on their HTTP status code.")
    parser.add_argument("urls", nargs="+", metavar="URL")
    parser.add_argument("-t", "--timeout", type=float, default=5.0,
                        help="seconds to wait for an answer (default 5)")
    parser.add_argument("-e", "--expect", type=parse_codes, default=DEFAULT_CODES, metavar="CODES",
                        help="status codes that mean up, e.g. 200 or 200-299,301 (default 200-399)")
    parser.add_argument("-r", "--retries", type=int, default=1,
                        help="how many times to retry before calling it down (default 1)")
    parser.add_argument("-i", "--interval", type=int, default=0,
                        help="keep checking every N seconds")
    parser.add_argument("-l", "--log", metavar="FILE", help="also append results to FILE")
    parser.add_argument("-k", "--insecure", action="store_true", help="don't verify TLS certificates")
    args = parser.parse_args(argv)

    for url in args.urls:
        if not url.startswith(("http://", "https://")):
            parser.error(f"{url}: URL has to start with http:// or https://")

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers, force=True)

    while True:
        all_up = True
        for url in args.urls:
            result = check_with_retries(url, retries=args.retries, timeout=args.timeout,
                                        expected=args.expect, verify_tls=not args.insecure)
            if result.up:
                log.info(result)
            else:
                log.warning(result)
                all_up = False

        if args.interval <= 0:
            return 0 if all_up else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
