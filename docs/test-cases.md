# Test cases

Test cases for the Wisecow deployment (problem statement 1) and the two scripts (problem statement 2), with the results I got.

Most of them run automatically in GitHub Actions. The results below are from these runs:

- ci-cd: https://github.com/Sergeb250/wisecow/actions/runs/45602638303
- scripts: https://github.com/Sergeb250/wisecow/actions/runs/45602638379

Environment: GitHub hosted `ubuntu-latest` runner, kind cluster, cert-manager v1.21.3, Traefik chart 42.4.3, Python 3.14. The argument checks (TC-17 to TC-20) were run by hand in bash.

## Problem statement 1: Wisecow on Kubernetes

| ID | Area | Test case | Steps | Expected result | Actual result | Status |
|---|---|---|---|---|---|---|
| TC-01 | Docker | Image builds | `docker build -t wisecow .` | Build finishes without errors | Built in the `build` job | Pass |
| TC-02 | Docker | Container serves a cow | Run the image with `-p 4499:4499`, `curl http://localhost:4499/` | HTTP 200, body has a fortune inside `<pre>` | Cow returned on the first request | Pass |
| TC-03 | CI | Image pushed to the registry on push to `main` | Push a commit, check GHCR | Image tagged `sha-<commit>` and `latest` | `ghcr.io/sergeb250/wisecow:sha-fdf94dc` and `latest` pushed | Pass |
| TC-04 | CI | Image can be pulled without login | Get an anonymous token from ghcr.io and request the `latest` manifest | HTTP 200 | HTTP 200 | Pass |
| TC-05 | Kubernetes | Manifests apply cleanly | `kubectl apply -k k8s/` | Namespace, deployment, service, issuers, certificates and ingress created | All 8 objects created | Pass |
| TC-06 | Kubernetes | Pods pass the `restricted` Pod Security Standard | Apply to the namespace labelled `pod-security.kubernetes.io/enforce: restricted` | Pods are admitted (non-root, read-only root fs, no capabilities) | Pods admitted and running | Pass |
| TC-07 | Kubernetes | Deployment becomes ready | `kubectl rollout status deployment/wisecow` | 2 of 2 replicas available, probes passing | Rolled out, 2/2 available | Pass |
| TC-08 | TLS | Certificate is issued | `kubectl wait --for=condition=Ready certificate/wisecow-tls` | Certificate Ready, secret `wisecow-tls` created | Condition met | Pass |
| TC-09 | TLS | App answers over HTTPS with a valid certificate | `curl --cacert ca.crt --resolve wisecow.local:8443:127.0.0.1 https://wisecow.local:8443/` | HTTP 200, certificate trusted by the CA, cow in the body | Cow returned, no certificate errors | Pass |
| TC-10 | TLS | Plain HTTP is redirected | `curl http://wisecow.local:8080/` | 301 or 308 to HTTPS | 301 | Pass |
| TC-11 | CD | New commit gets deployed | Push a commit and check which image the deploy job uses | Deployment runs the image built from that commit | `sha-fdf94dc` deployed by the same run | Pass |
| TC-12 | CI | Pull requests build but don't push | Open a PR against `main` | Build and smoke test run, push and deploy are skipped | No PR opened yet | Not run |

## Problem statement 2: scripts/system_health.sh

| ID | Test case | Steps | Expected result | Actual result | Status |
|---|---|---|---|---|---|
| TC-13 | Everything under its threshold | `system_health.sh -c 100 -m 100 -d 100 -s systemd -l health.log` | Only OK and INFO lines, exit code 0 | CPU 5%, memory 6%, disks 7-40%, 177 processes, systemd running. Exit 0 | Pass |
| TC-14 | Threshold exceeded raises an alert | `system_health.sh -d 0 -l health.log` | ALERT for every filesystem, exit code 1 | 3 ALERT lines (/, /boot, /boot/efi), exit 1 | Pass |
| TC-15 | Required process check | `-s systemd` on the runner | `systemd is running` | `[OK] systemd is running` | Pass |
| TC-16 | Results written to the log file | Run with `-l health.log`, read the file | Same lines as the console, with timestamps | Log matched console output | Pass |
| TC-17 | Non-numeric threshold | `system_health.sh -c abc` | Error message, exit code 2 | `not a whole number: abc`, exit 2 | Pass |
| TC-18 | Unknown option | `system_health.sh -x` | Error and usage, exit code 2 | `unknown option -x` and usage, exit 2 | Pass |
| TC-19 | Option without a value | `system_health.sh -l` | Error, exit code 2 | `option -l needs a value`, exit 2 | Pass |
| TC-20 | Help | `system_health.sh -h` | Usage text, exit code 0 | Usage shown, exit 0 | Pass |
| TC-21 | Static analysis | `shellcheck scripts/*.sh` | No warnings | Clean after fixing D-01 | Pass |

## Problem statement 2: scripts/app_health_check.py

TC-22 to TC-30 are unit tests in `tests/test_app_health_check.py`. They run against a local test server.

| ID | Test case | Input | Expected result | Actual result | Status |
|---|---|---|---|---|---|
| TC-22 | Healthy app | GET returns 200 | UP | UP, HTTP 200 | Pass |
| TC-23 | Client and server errors | 404, 500, 503 | DOWN with the status code | DOWN 404 / 500 / 503 | Pass |
| TC-24 | Redirects are followed | 302 to a 200 page | UP, HTTP 200 | UP, HTTP 200 | Pass |
| TC-25 | Custom expected codes | `expected={404}` on a 404, `expected={204}` on a 200 | UP, then DOWN | UP, then DOWN | Pass |
| TC-26 | Slow app | Server sleeps 2 s, timeout 0.5 s | DOWN, no status code, error message set | DOWN, no status code, error set | Pass |
| TC-27 | App not running | Port with nothing listening | DOWN | DOWN, no status code | Pass |
| TC-28 | Wisecow style response | `HTTP/1.1 200` with no reason phrase and no headers | UP | UP, HTTP 200 | Pass |
| TC-29 | Retries | Healthy URL with 3 retries | Returns UP on the first try | UP | Pass |
| TC-30 | Exit code | One healthy URL / one healthy and one broken | 0 / 1 | 0 / 1 | Pass |
| TC-31 | Real public sites | `app_health_check.py https://github.com https://api.github.com/zen` | Both UP, exit 0 | Both UP (HTTP 200) | Pass |
| TC-32 | Closed port | `app_health_check.py http://127.0.0.1:9 -t 2 -r 0` | DOWN, exit 1 | DOWN, connection refused, exit 1 | Pass |
| TC-33 | Deployed Wisecow behind the ingress | `app_health_check.py https://wisecow.local:8443 --insecure --expect 200` | UP | UP, HTTP 200, 108 ms | Pass |

## Defects found and fixed

| ID | Found by | Problem | Fix |
|---|---|---|---|
| D-01 | TC-21 | shellcheck SC2009: zombie count used `ps \| grep` | Counted with awk instead (776ff37) |
| D-02 | TC-13 | `/sys/firmware/efi/efivars` showed up as a disk, so a pseudo filesystem could raise disk alerts | Excluded `efivarfs` from `df` (039ce33) |
| D-03 | TC-23 | Python warned about unclosed responses (ResourceWarning) for 4xx/5xx | Close the `HTTPError` response (039ce33) |

## Summary

33 test cases: 32 passed, 1 not run (TC-12). 3 defects found, all fixed.
