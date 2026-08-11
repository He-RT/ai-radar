# Observability

## Access

The observability profile is private by design. On an administrator workstation, use a trusted SSH account and tunnel ports:

~~~sh
ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 ADMIN_USER@VPS_HOST
~~~

Open Grafana at http://127.0.0.1:3001 and Prometheus at http://127.0.0.1:9090. Do not proxy either through Caddy or open their firewall ports.

## Signals

The supplied profile provides:

- API and host scrape availability through Prometheus;
- host memory, filesystem, CPU, and network signals through node-exporter;
- structured container logs through Promtail and Loki;
- a provisioned service-health dashboard.

The API must expose non-sensitive metrics on the internal application network only. At minimum instrument request latency/error rate, queue depth and oldest age, job attempts/failures, LLM call outcome/latency/cost, source-ingestion freshness, and correction publication counts.

## Initial alert thresholds

Treat these as starting points and calibrate after two weeks:

- API or node scrape unavailable for 5 minutes: page.
- Available host memory below 1 GiB for 10 minutes: urgent.
- Filesystem free space below 15 percent: urgent.
- Oldest critical queue job above 30 minutes: page.
- Job failure rate above 2 percent for 10 minutes: investigate.
- LLM provider error rate above 10 percent for 5 minutes: enable degraded mode.

Alerts must route to an owned, tested channel before relying on them for on-call coverage.

## Log practice

Caddy and application logs should be JSON and include request/job IDs, immutable image digest, event ID, source ID, and error class. Never log API keys, authorization headers, raw user prompts, source credentials, or full private content. Retain security-relevant logs according to the approved policy; Loki's supplied local retention is only seven days and is not a compliance archive.
