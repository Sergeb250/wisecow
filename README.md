# Wisecow on Kubernetes

[![ci-cd](https://github.com/Sergeb250/wisecow/actions/workflows/ci-cd.yaml/badge.svg)](https://github.com/Sergeb250/wisecow/actions/workflows/ci-cd.yaml)
[![scripts](https://github.com/Sergeb250/wisecow/actions/workflows/scripts.yaml/badge.svg)](https://github.com/Sergeb250/wisecow/actions/workflows/scripts.yaml)

My solution to the AccuKnox QA Trainee practical assessment.

Wisecow (`wisecow.sh`, from [nyrahul/wisecow](https://github.com/nyrahul/wisecow)) is a small bash web server that answers every request on port 4499 with a `fortune` said by `cowsay`. The app itself is unchanged. This repo adds the container image, Kubernetes manifests, TLS and a CI/CD pipeline (problem statement 1), and two monitoring scripts (problem statement 2).

```
Dockerfile                     container image
k8s/                           namespace, deployment, service, certificates, ingress (kustomize)
k8s/optional/                  Let's Encrypt issuer for a real domain
ci/traefik-values.yaml         ingress controller settings
.github/workflows/ci-cd.yaml   build, push, deploy
scripts/                       problem statement 2
tests/                         tests for the app health checker
```

## Problem statement 1

### Docker

```bash
docker build -t wisecow .
docker run --rm -p 4499:4499 wisecow
curl http://localhost:4499
```

The image is `debian:trixie-slim` with `fortune-mod`, `cowsay` and `netcat-openbsd`. It runs as a non-root user (uid 10001), and `tini` is PID 1 so the container stops straight away on `docker stop` or a pod shutdown.

### Kubernetes

The cluster needs [cert-manager](https://cert-manager.io) and an ingress controller. I used Traefik because ingress-nginx was retired in March 2026. Another controller works too if you change `ingressClassName` and the two Traefik annotations in `k8s/ingress.yaml`.

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.3/cert-manager.yaml
helm repo add traefik https://traefik.github.io/charts
helm install traefik traefik/traefik -n traefik --create-namespace -f ci/traefik-values.yaml

kubectl apply -k k8s/
kubectl -n wisecow get pods,svc,ingress,certificate
```

Everything goes into the `wisecow` namespace:

- **Deployment**: 2 replicas, readiness and liveness probes on port 4499, CPU and memory limits, read-only root filesystem, no Linux capabilities, no service account token. The namespace enforces the `restricted` Pod Security Standard.
- **Service**: ClusterIP, port 80 to 4499. Without the ingress you can still reach it with `kubectl -n wisecow port-forward svc/wisecow 8080:80`.
- **Ingress**: `wisecow.local`, HTTPS only.
- **Issuers and certificates** for TLS.

### TLS

TLS ends at the ingress. cert-manager creates a small private CA in the namespace (a self-signed issuer signs the `wisecow-ca` certificate, then a CA issuer uses it) and issues the `wisecow-tls` certificate for `wisecow.local`. Traefik serves it on port 443 and redirects port 80 to HTTPS.

To try it locally:

```bash
kubectl -n wisecow get secret wisecow-tls -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
kubectl -n traefik port-forward svc/traefik 8443:443 &
curl --cacert ca.crt --resolve wisecow.local:8443:127.0.0.1 https://wisecow.local:8443
```

For a real domain, point DNS at the ingress and change `wisecow.local` in `k8s/ingress.yaml` and `k8s/tls.yaml`. Then set your email in `k8s/optional/letsencrypt-issuer.yaml`, apply it, and change the `issuerRef` of `wisecow-tls` to `name: letsencrypt, kind: ClusterIssuer`.

### CI/CD

`.github/workflows/ci-cd.yaml` runs on every push to `main`. Pull requests only get the build and smoke test.

1. **Build and push image**: builds the image, starts it and checks that it answers with a cow. It then pushes `ghcr.io/sergeb250/wisecow:sha-<commit>` and `:latest` to the GitHub Container Registry. The login uses `GITHUB_TOKEN`, so no extra secrets are needed.
2. **Deploy to kind**: creates a kind cluster and installs cert-manager and Traefik. It loads the new image and applies `k8s/` with the new tag, then waits for the rollout and the certificate. Finally it calls the app over HTTPS, checking the certificate against the CA, and checks that plain HTTP gets a 301 to HTTPS.
3. **Deploy to cluster**: runs the same deployment against a real cluster. It only runs when the repository variable `DEPLOY_TO_CLUSTER` is `true` and the secret `KUBE_CONFIG` holds a base64 encoded kubeconfig.

The image is public: `docker pull ghcr.io/sergeb250/wisecow:latest`.

## Problem statement 2

I picked **1. System Health Monitoring** (bash) and **4. Application Health Checker** (python, standard library only).

### scripts/system_health.sh

Checks CPU usage (two `/proc/stat` samples a second apart), memory (`MemAvailable`), disk usage for every real filesystem, the number of processes, zombie processes and, optionally, processes that must be running. Every result goes to the console and the log file. Anything over its threshold is logged as `ALERT`, together with the top processes for CPU and memory alerts.

```bash
./scripts/system_health.sh                      # defaults: cpu 80, memory 80, disk 80, 500 processes
./scripts/system_health.sh -c 70 -d 90 -s sshd,cron -l /var/log/system_health.log
./scripts/system_health.sh -i 60                # check every minute
```

Output from a CI run (`-s systemd`, then again with `-d 0` to force disk alerts):

```
2026-11-25 11:14:57 [INFO] checking runnervm0hi8g
2026-11-25 11:14:58 [OK] CPU usage 5%
2026-11-25 11:14:58 [OK] memory usage 6% (987 MB of 15983 MB)
2026-11-25 11:14:58 [OK] disk usage on / 40%
2026-11-25 11:14:58 [OK] disk usage on /boot 10%
2026-11-25 11:14:58 [OK] disk usage on /boot/efi 7%
2026-11-25 11:14:58 [OK] 177 processes running
2026-11-25 11:14:58 [OK] systemd is running
2026-11-25 11:14:58 [INFO] done, everything within limits
2026-11-25 11:14:58 [INFO] checking runnervm0hi8g
2026-11-25 11:15:00 [OK] CPU usage 0%
2026-11-25 11:15:00 [OK] memory usage 6% (987 MB of 15983 MB)
2026-11-25 11:15:00 [ALERT] disk usage on / is 40% (threshold 0%)
2026-11-25 11:15:00 [ALERT] disk usage on /boot is 10% (threshold 0%)
2026-11-25 11:15:00 [ALERT] disk usage on /boot/efi is 7% (threshold 0%)
2026-11-25 11:15:00 [OK] 177 processes running
2026-11-25 11:15:00 [INFO] done, 3 alert(s)
```

It exits with 1 when there was an alert, so it can go in cron and mail the output, for example.

### scripts/app_health_check.py

Sends a GET request to each URL and reports **UP** when the status code is an expected one (any 2xx or 3xx by default, redirects are followed). It reports **DOWN** on 4xx or 5xx, timeouts, refused connections and TLS errors. It retries once before calling an app down, to ignore a single blip.

```bash
./scripts/app_health_check.py https://github.com http://localhost:4499
./scripts/app_health_check.py https://wisecow.local:8443 --insecure
./scripts/app_health_check.py http://localhost:8080/health --expect 200 --interval 30 --log health.log
```

```
2026-11-25 11:12:22  UP    https://github.com  (HTTP 200, 84 ms)
2026-11-25 11:12:22  UP    https://api.github.com/zen  (HTTP 200, 82 ms)
2026-11-25 11:12:22  DOWN  http://127.0.0.1:9  ([Errno 111] Connection refused, 7 ms)
```

Exit code 0 means everything is up. The deploy job also runs it against the Wisecow app behind the ingress. Run `./scripts/app_health_check.py -h` for all options.

Tests: `python3 -m unittest discover -s tests -v`. The `scripts` workflow runs shellcheck, the tests and both scripts on every change in `scripts/` or `tests/`.
