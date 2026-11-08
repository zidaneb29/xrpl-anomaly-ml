# Phase 4C reproducible service verification

The service uses the Phase 4B FastAPI, Starlette, Pydantic and Uvicorn versions. The core scorers use the standard library. The service lock pins all 14 runtime packages and their wheel hashes. FastAPI requires the OpenTelemetry API package. The service configures no exporter or tracking backend. The Windows plotting and MLflow locks remain separate.

## Local API on Windows

Use x64 CPython 3.14.7 and pip. From the repository root in PowerShell:

```powershell
$basePython = 'C:/path/to/python.exe'
& $basePython -m venv .venv-phase4c
$python = './.venv-phase4c/Scripts/python.exe'
& $python -m pip install --only-binary=:all: --require-hashes -r requirements-service-py314.txt
& $python -m pip check
$env:PYTHONPATH = 'src'
& $python -B -m uvicorn xrpl_anomaly.service:create_app --factory --host 127.0.0.1 --port 8000 --http h11 --no-proxy-headers --no-access-log
```

The default path is `artifacts/phase4a/models/baseline-full.json`. Before startup, set `XRPL_MODEL_PATH` to a verified local file to use another bundle. The [Phase 4A guide](phase4a.md#model-bundle-v1) describes the approved bundles and how to recover them from the local frozen outputs. Compare the file's SHA-256 to a trusted record before loading. From another shell, check `Invoke-RestMethod http://127.0.0.1:8000/health` and use the [Phase 4B scoring example](phase4b.md#http-contract).

## Local Linux container

Use Docker Engine 28 or newer, or Docker Desktop with a Linux engine meeting that version requirement. Check with `docker version` and use a local daemon. The image targets Linux amd64 and pins the official CPython 3.14.7 slim Trixie image by digest. The lock also supports conventional x64 CPython 3.14 on Windows and glibc x86-64 Linux. ARM, Alpine, free-threaded Python and other Python minor versions require their own wheel verification. Use native amd64 for the supported Docker path.

```powershell
docker version
docker build --platform linux/amd64 -t xrpl-anomaly-ml:local .
$model = (Resolve-Path 'artifacts/phase4a/models/baseline-full.json').Path
Get-FileHash -Algorithm SHA256 -LiteralPath $model
docker run --rm --name xrpl-local --read-only --cap-drop=ALL --security-opt=no-new-privileges `
  --publish 127.0.0.1:8000:8000 `
  --mount "type=bind,source=$model,target=/models/model.json,readonly" xrpl-anomaly-ml:local
```

On Linux use the same Docker arguments with an absolute local file path and the shell's line continuation syntax. The daemon must be able to read the mount source, and the file must be readable by container UID/GID 10001. Mount one bundle at a time. The image sets `XRPL_MODEL_PATH=/models/model.json`, validates that file at startup, and exits if it is missing or malformed. The internal health probe uses IPv4 loopback and checks the readiness response. In a second shell run `docker inspect --format '{{.State.Health.Status}}' xrpl-local` and check the published `/health` endpoint. Stop with Ctrl+C or `docker stop xrpl-local`.

Uvicorn listens on `0.0.0.0:8000` inside the container so Docker can forward traffic to it. Publish explicitly on `127.0.0.1` on the host. Keep the container on a trusted local Docker network. Containers on a shared network can reach the internal listener, and a client can supply its own Host header. The service has no authentication or TLS. Docker versions before 28 have a documented localhost publication caveat on the same layer-2 segment. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)

The API keeps the Phase 4B Host allowlist of `127.0.0.1`, `localhost` and `[::1]`, with optional ports. The published listener in this command uses host IPv4. The existing 8 KiB body limit, duplicate-key rejection, feature schema validation and calibration logic apply inside the container.

## Verification

Run from the repository root with the service environment. Set `PYTHONPATH=src` in the shell first.

```powershell
& $python -B -m unittest discover -s tests -v
```

For the complete Windows plotting checks, also install `requirements-phase2-plots-win-py314.txt` into the isolated test environment with the same binary and hash options. Linux exercises the service and all dependency-free fixtures. The optional plotting checks run on Windows. The deadline/retry fixture uses a loopback server, so the test runner needs permission to open local sockets.

The GitHub workflow runs on pushes and pull requests using Windows x64 and Ubuntu x64. It checks dependency consistency, imports the service and runs the offline fixture suite. The Ubuntu job also builds the image locally and uses a deterministic synthetic bundle to test readiness, Host handling, missing-bundle startup failure and exact scoring parity. The fixture comes from the existing unit-test generator and is mounted only for the test. CI uses read-only repository permissions, pinned actions and no XRPL access, application credentials or private inputs. It downloads tools and dependencies during setup. `.gitignore` keeps the local instructions, data, environment, databases and artifacts out of Git. The Docker build context is allowlisted to package source, the service lock and Docker build definitions.

For local checks against the three frozen bundles, set the following from the same shell:

```powershell
$env:XRPL_TEST_FROZEN_MODELS = 'artifacts/phase4a/models'
# Set this only after building the local image and checking the Docker daemon.
$env:XRPL_TEST_IMAGE = 'xrpl-anomaly-ml:local'
& $python -B -m unittest discover -s tests -p test_phase4c.py -v
Remove-Item Env:XRPL_TEST_IMAGE, Env:XRPL_TEST_FROZEN_MODELS -ErrorAction SilentlyContinue
```

With only the frozen model directory set, the test compares direct scoring and the local API for all three bundles. With the image set as well, it compares responses over the Docker-published port using those same mounted bytes. The test checks exact scores, alert decisions and model metadata. The synthetic Docker checks can run with just the image variable. The separate historical verifier (`python -B -m xrpl_anomaly.verify_packaged`) additionally needs the private historical SQLite databases and Phase 3B.3 clean score table. It replays features in read-only mode and checks 71,031 frozen scores and 18 operating alert counts. Use it when verifying the full historical contract.

The Docker daemon was unavailable in the Phase 4C Windows workspace. The image build, Linux runtime health and Docker parity checks require a usable daemon. The GitHub workflow is prepared for future publication.
