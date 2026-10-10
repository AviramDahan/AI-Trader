"""Compress only large public scanner projections, never authenticated writes."""
from starlette.middleware.gzip import GZipMiddleware


class ScannerReadCompression:
    PATHS = frozenset(("/api/scanner/dashboard", "/api/scanner/research"))

    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1000, compresslevel=5)

    async def __call__(self, scope, receive, send):
        allowed = (scope["type"] == "http" and scope.get("method") == "GET"
                   and scope.get("path") in self.PATHS)
        # Starlette's substring check does not exclude gzip;q=0. Respect clients
        # explicitly declining gzip, without compressing private/other routes.
        accepted = False
        for name, value in scope.get("headers", []):
            if name.lower() != b"accept-encoding":
                continue
            for coding in value.decode("latin-1").lower().split(","):
                parts = [part.strip() for part in coding.split(";")]
                if parts[0] != "gzip":
                    continue
                try:
                    quality = next((float(p[2:]) for p in parts[1:] if p.startswith("q=")), 1)
                    accepted = 0 < quality <= 1
                except ValueError:
                    accepted = False
        await (self.compressed if allowed and accepted else self.app)(scope, receive, send)
