"""Disposable process for one bounded, read-only HTTP exchange."""
import http.client
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(endpoint, payload, limit, timeout):
    request = Request(endpoint, payload.encode(), {"Content-Type": "application/json",
                                                  "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            if response.headers.get("Content-Encoding", "identity") != "identity":
                return ["invalid", "unexpected response encoding"]
            while limit:
                chunk = response.read1(min(65536, limit))
                if not chunk:
                    if response.length:
                        return ["retry", "truncated response"]
                    return ["ok"]
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                limit -= len(chunk)
            return ["limit"]
    except HTTPError as exc:
        with exc:
            return ["http", exc.code, exc.headers.get("Retry-After", "0")]
    except (OSError, URLError, http.client.HTTPException) as exc:
        return ["retry", str(exc)]


if __name__ == "__main__":
    _, endpoint, payload, limit, timeout = sys.argv
    print(json.dumps(fetch(endpoint, payload, int(limit), float(timeout))), file=sys.stderr)
