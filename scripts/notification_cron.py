from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    base_url = os.getenv("PUBLIC_URL", "https://digit-laboral-app.onrender.com").rstrip("/")
    token = os.getenv("NOTIFICATION_CRON_TOKEN", "").strip()
    if not token:
        print("NOTIFICATION_CRON_TOKEN is required.", file=sys.stderr)
        return 2

    request = Request(
        f"{base_url}/internal/cron/notifications",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DigitLaboral-NotificationCron/1.0",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            payload = response.read().decode("utf-8")
            if not 200 <= response.status < 300:
                print(f"Notification worker returned HTTP {response.status}: {payload}", file=sys.stderr)
                return 1
            # Keep run logs useful without printing the shared authorization token.
            print(json.dumps(json.loads(payload), ensure_ascii=False))
            return 0
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        print(f"Notification worker returned HTTP {exc.code}: {detail}", file=sys.stderr)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"Notification worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
