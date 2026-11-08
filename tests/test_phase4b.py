import importlib.util
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from test_phase4a import ROWS, SCHEMA, fixture
from xrpl_anomaly import baseline
from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION, WINDOW
from xrpl_anomaly.model_artifact import BASELINE_CONFIG, load
from xrpl_anomaly.package_models import save

if importlib.util.find_spec("fastapi"):
    from xrpl_anomaly.service import MAX_REQUEST_BYTES, create_app


async def request(app, method, path, *chunks, media_type="application/json", host="127.0.0.1:8000"):
    messages = []
    pending = iter(chunks or (b"",))
    next_chunk = next(pending)

    async def receive():
        nonlocal next_chunk
        body, next_chunk = next_chunk, next(pending, None)
        return {"type": "http.request", "body": body, "more_body": next_chunk is not None}

    async def send(message):
        messages.append(message)

    headers = [(b"content-type", media_type.encode())]
    if host is not None:
        headers.append((b"host", host.encode()))
    await app({"type": "http", "method": method, "path": path, "query_string": b"",
               "headers": headers, "scheme": "http",
               "server": ("localhost", 80), "http_version": "1.1"}, receive, send)
    body = b"".join(msg["body"] for msg in messages[1:])
    content_type = dict(messages[0]["headers"]).get(b"content-type", b"")
    return messages[0]["status"], json.loads(body) if content_type == b"application/json" else body.decode()


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

    async def test_allowed_hosts(self):
        save(self.path, self.bundle)
        app = create_app(self.path)
        body = json.dumps(self.payload).encode()
        async with app.router.lifespan_context(app):
            for host in ("127.0.0.1:8000", "LOCALHOST", "localhost:8000", "[::1]:8000"):
                with self.subTest(host=host):
                    self.assertEqual((await request(app, "POST", "/v1/score", body, host=host))[0], 200)
            for host in (None, "audit.invalid", "localhost.audit.invalid:8000", "0.0.0.0", "localhost:bad"):
                with self.subTest(host=host):
                    self.assertEqual(await request(app, "GET", "/health", host=host),
                                     (400, "Invalid host header"))

    async def test_duplicate_json_keys(self):
        save(self.path, self.bundle)
        app = create_app(self.path)
        valid = json.dumps(self.payload).encode()
        async with app.router.lifespan_context(app):
            self.assertEqual((await request(app, "POST", "/v1/score", valid[:50], valid[50:]))[0], 200)
            for prefix in (b'{"feature_schema_version": 1, ', br'{"\u0066eature_schema_version": 1, '):
                self.assertEqual((await request(app, "POST", "/v1/score", prefix, valid[1:]))[0], 422)
            # A second transaction_id must fail even though its last value is valid.
            duplicate = valid[:-1] + b', "transaction_id": null, "transaction_id": null}'
            self.assertEqual((await request(app, "POST", "/v1/score", duplicate))[0], 422)

    async def test_scoring_openapi_contract(self):
        app = create_app(self.path)
        status, schema = await request(app, "GET", "/openapi.json")
        self.assertEqual(status, 200)
        operation = schema["paths"]["/v1/score"]["post"]
        request_body = operation["requestBody"]
        self.assertTrue(request_body["required"])
        self.assertIn(str(MAX_REQUEST_BYTES), request_body["description"])
        body = request_body["content"]["application/json"]["schema"]
        self.assertFalse(body["additionalProperties"])
        self.assertEqual(set(body["required"]), {"feature_schema_version", "feature_names", "values"})
        properties = body["properties"]
        self.assertEqual(properties["feature_schema_version"]["const"], SCHEMA_VERSION)
        for key in ("feature_names", "values"):
            self.assertEqual(properties[key]["minItems"], 21)
            self.assertEqual(properties[key]["maxItems"], 21)
            self.assertIs(properties[key]["items"], False)
        self.assertEqual(tuple(item["const"] for item in properties["feature_names"]["prefixItems"]), FEATURES)
        values = properties["values"]["prefixItems"]
        self.assertEqual(tuple(item["title"] for item in values), FEATURES)
        self.assertEqual(values[6], {"title": "sender_recency_seconds", "type": "integer",
                                     "minimum": 0, "maximum": WINDOW})
        self.assertEqual(values[7]["maximum"], 1)
        self.assertEqual(values[19]["maximum"], 1)
        identity = properties["transaction_id"]["anyOf"]
        self.assertEqual(identity[0]["pattern"], "^[0-9A-Fa-f]{64}$")
        self.assertEqual(identity[1]["type"], "null")
        responses = operation["responses"]
        models = schema["components"]["schemas"]

        def response_schema(status):
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            return models[ref.rsplit("/", 1)[-1]]

        score = response_schema("200")
        self.assertEqual(set(score["required"]),
                         {"anomaly_score", "model_id", "model_type", "model_version",
                          "feature_schema_version", "artifact_sha256", "alert"})
        self.assertEqual(score["properties"]["anomaly_score"]["type"], "number")
        self.assertEqual({item["type"] for item in score["properties"]["alert"]["anyOf"]}, {"boolean", "null"})
        for status in ("400", "413", "415", "422"):
            self.assertEqual(response_schema(status)["properties"]["detail"]["type"], "string")
        self.assertEqual(responses["400"]["content"]["text/plain"]["schema"]["type"], "string")

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
