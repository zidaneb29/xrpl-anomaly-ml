import importlib.util
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from test_phase4a import ROWS, SCHEMA, fixture
from xrpl_anomaly import baseline
from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION
from xrpl_anomaly.model_artifact import BASELINE_CONFIG, load
from xrpl_anomaly.package_models import save

if importlib.util.find_spec("fastapi"):
    from xrpl_anomaly.service import MAX_REQUEST_BYTES, create_app


async def request(app, method, path, *chunks, media_type="application/json"):
    messages = []
    pending = iter(chunks or (b"",))
    next_chunk = next(pending)

    async def receive():
        nonlocal next_chunk
        body, next_chunk = next_chunk, next(pending, None)
        return {"type": "http.request", "body": body, "more_body": next_chunk is not None}

    async def send(message):
        messages.append(message)

    await app({"type": "http", "method": method, "path": path, "query_string": b"",
               "headers": [(b"content-type", media_type.encode())], "scheme": "http",
               "server": ("localhost", 80), "http_version": "1.1"}, receive, send)
    return messages[0]["status"], json.loads(b"".join(msg["body"] for msg in messages[1:]))


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "optional FastAPI environment required")
class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(dir="."))
        self.path = Path(directory) / "model.json"
        self.boundary = "AB" * 32
        self.parameters = baseline.fit(ROWS, FEATURES)
        self.payload = {"feature_schema_version": SCHEMA_VERSION, "feature_names": FEATURES, "values": ROWS[20]}
        score = baseline.score(ROWS[20], FEATURES, self.parameters)[0]
        self.bundle = fixture("baseline-full", "robust_baseline", BASELINE_CONFIG, self.parameters,
                              list(FEATURES[1:]), baseline.alert_key(score, self.boundary))

    async def test_model_metadata_and_scoring_parity(self):
        save(self.path, self.bundle)
        detector = load(self.path)
        app = create_app(self.path)
        self.assertEqual((await request(app, "GET", "/health"))[0], 503)
        async with app.router.lifespan_context(app):
            self.assertEqual(await request(app, "GET", "/health"), (200, {"status": "ready"}))
            status, metadata = await request(app, "GET", "/v1/model")
            self.assertEqual(status, 200)
            self.assertEqual(metadata["artifact_sha256"], detector.artifact_sha256)
            self.assertEqual(metadata["feature_names"], list(FEATURES))
            self.assertNotIn("cutoff", metadata)
            for values in (ROWS[20], ROWS[0], ROWS[128]):
                for identity in (None, self.boundary.lower(), "AA" * 32):
                    body = json.dumps(dict(self.payload, values=values, transaction_id=identity)).encode()
                    status, response = await request(app, "POST", "/v1/score", body)
                    expected = detector.score(values, **SCHEMA)
                    alert = None if identity is None else detector.alerts(expected, identity=identity.upper())
                    self.assertEqual((status, response), (200, dict(asdict(expected), alert=alert)))
            self.assertFalse((await request(app, "POST", "/v1/score", json.dumps(
                dict(self.payload, transaction_id=self.boundary)).encode()))[1]["alert"])
        self.assertEqual((await request(app, "GET", "/health"))[0], 503)

    async def test_bad_requests(self):
        save(self.path, self.bundle)
        app = create_app(self.path)
        async with app.router.lifespan_context(app):
            cases = [dict(self.payload, feature_schema_version=True),
                     dict(self.payload, feature_schema_version=2),
                     dict(self.payload, feature_names=FEATURES[::-1]),
                     dict(self.payload, transaction_id="identity"),
                     dict(self.payload, values=[]), dict(self.payload, extra="forbidden")]
            for index, invalid in ((0, "3"), (0, True), (0, None), (0, float("inf")),
                                   (6, 3.0), (7, 2), (19, 1.1)):
                row = list(ROWS[20])
                row[index] = invalid
                cases.append(dict(self.payload, values=row))
            for body in (b"{", b'{"values":null}', *(json.dumps(case).encode() for case in cases)):
                with self.subTest(body=body):
                    self.assertEqual((await request(app, "POST", "/v1/score", body))[0], 422)
            self.assertEqual((await request(app, "POST", "/v1/score", b"{}", media_type="text/plain"))[0], 415)
            self.assertEqual((await request(app, "POST", "/v1/score", b" " * MAX_REQUEST_BYTES, b" "))[0], 413)
            status, schema = await request(app, "GET", "/openapi.json")
            self.assertEqual(status, 200)
            self.assertTrue(schema["paths"]["/v1/score"]["post"]["requestBody"]["required"])

    async def test_startup_fails_closed_and_recovers_with_valid_artifact(self):
        app = create_app(self.path)
        with self.assertRaises(FileNotFoundError):
            async with app.router.lifespan_context(app):
                self.fail("missing model should prevent startup")
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            async with app.router.lifespan_context(app):
                self.fail("invalid model should prevent startup")
        self.path.unlink()
        save(self.path, self.bundle)
        async with app.router.lifespan_context(app):
            self.assertEqual((await request(app, "GET", "/health"))[0], 200)
