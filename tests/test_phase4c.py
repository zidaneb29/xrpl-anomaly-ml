"""Service release checks with explicit opt-ins for Docker and frozen bundles."""
import asyncio
import http.client
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_phase4a import ROWS, SCHEMA
from test_phase4b import request, service_fixture
from xrpl_anomaly.model_artifact import load
from xrpl_anomaly.package_models import save

IMAGE = os.getenv("XRPL_TEST_IMAGE")
FROZEN = os.getenv("XRPL_TEST_FROZEN_MODELS")
MODEL_FILES = ("baseline-full.json", "isolation-full-7.json", "isolation-full-29.json")


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=30)


def http_request(port, method, path, body=None, host=None):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        headers = {"Content-Type": "application/json"}
        if host is not None:
            headers["Host"] = host
        client.request(method, path, body, headers)
        response = client.getresponse()
        raw = response.read()
        if response.headers.get("Content-Type") == "application/json":
            return response.status, json.loads(raw)
        return response.status, raw.decode()


class ReleaseTests(unittest.TestCase):
    @unittest.skipUnless(IMAGE, "set XRPL_TEST_IMAGE to a locally built image")
    def test_container_synthetic_parity(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(dir="."))
        path = Path(directory) / "model.json"
        bundle, boundary = service_fixture()
        save(path, bundle)
        self.check_parity(path, boundary, self.start_container(path))

    @unittest.skipUnless(IMAGE, "set XRPL_TEST_IMAGE to a locally built image")
    def test_container_rejects_missing_bundle(self):
        result = docker("run", "--rm", "--pull=never", "--network=none", IMAGE, check=False)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("FileNotFoundError", result.stderr)
        self.assertIn("/models/model.json", result.stderr)

    @unittest.skipUnless(FROZEN, "set XRPL_TEST_FROZEN_MODELS to the approved local model directory")
    def test_frozen_bundle_parity(self):
        for name in MODEL_FILES:
            with self.subTest(bundle=name):
                path = Path(FROZEN) / name
                port = self.start_container(path) if IMAGE else None
                self.check_parity(path, "AB" * 32, port)

    def start_container(self, path):
        self.assertTrue(path.is_file(), path)
        name = f"xrpl-verify-{uuid4().hex}"
        self.addCleanup(docker, "rm", "-f", name, check=False)
        result = docker(
            "run", "-d", "--pull=never", "--name", name, "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "-p", "127.0.0.1::8000",
            "--mount", f"type=bind,source={path.resolve()},target=/models/model.json,readonly",
            IMAGE, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", "--format={{json .State}}", name).stdout)
            if state["Health"]["Status"] == "healthy":
                published = docker("port", name, "8000/tcp").stdout.strip()
                host, _, port = published.rpartition(":")
                self.assertEqual(host, "127.0.0.1")
                port = int(port)
                self.assertEqual(http_request(port, "GET", "/health"), (200, {"status": "ready"}))
                self.assertEqual(http_request(port, "GET", "/health", host="audit.invalid"), (400, "Invalid host header"))
                return port
            if not state["Running"] or state["Health"]["Status"] == "unhealthy":
                break
            time.sleep(0.5)
        logs = docker("logs", name, check=False)
        self.fail(f"Container failed to become healthy: {state}\n{logs.stdout}\n{logs.stderr}")

    def check_parity(self, path, boundary, port):
        from xrpl_anomaly.service import create_app

        detector = load(path)

        async def compare():
            # Match the environment-based configuration used by the container.
            with patch.dict(os.environ, {"XRPL_MODEL_PATH": str(path.resolve())}):
                app = create_app()
                async with app.router.lifespan_context(app):
                    metadata = await request(app, "GET", "/v1/model")
                    self.assertEqual(metadata[0], 200)
                    self.assertEqual(metadata[1]["artifact_sha256"], detector.artifact_sha256)
                    if port is not None:
                        self.assertEqual(http_request(port, "GET", "/v1/model"), metadata)
                    for values in (ROWS[0], ROWS[20], ROWS[128]):
                        score = detector.score(values, **SCHEMA)
                        for identity in (None, boundary.lower(), "AA" * 32):
                            body = json.dumps(dict(SCHEMA, values=values, transaction_id=identity)).encode()
                            alert = None if identity is None else detector.alerts(score, identity=identity.upper())
                            expected = (200, dict(asdict(score), alert=alert))
                            self.assertEqual(await request(app, "POST", "/v1/score", body), expected)
                            if port is not None:
                                self.assertEqual(http_request(port, "POST", "/v1/score", body), expected)
                self.assertEqual((await request(app, "GET", "/health"))[0], 503)

        asyncio.run(compare())
