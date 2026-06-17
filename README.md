# ConfigProbe

Fetches free proxy/VPN subscription URLs, deduplicates configs, and tests each one for reachability and IP redirection.
Supports vless, vmess, shadowsocks, trojan, hysteria2, SSR, SOCKS, and TUIC protocols.
Results are exported as CSV/JSON with geo-IP enrichment (country, city, ASN, datacenter flag).

## How to Run

### 1. Add subscription URLs

Create `subscriptions.txt` (one URL per line):

```text
https://example.com/sub1
https://example.com/sub2
```

### 2. Single container (basic)

```bash
docker compose run --rm configprobe \
  -i /subs/subscriptions.txt \
  -w 10 \
  -o /results \
  -f both
```

### 3. Parallel containers (recommended for large lists)

Run 12 containers in parallel — fetch once, split the work, merge results:

```bash
python scripts/orchestrate.py 12
```

Smoke test with 15 configs per shard:

```bash
python scripts/orchestrate.py 12 15
```

Options:

```bash
python scripts/orchestrate.py [containers] [limit_per_shard] \
  --workers 50 \
  --outdir config_results \
  --progress-interval 250
```

Results are written to `config_results/merged/results.csv` and `results.json`.

### 4. Build the image manually

```bash
docker compose build configprobe
```

## Architecture

```text
src/
├── main.py                   # Docker entrypoint & CLI
├── configprobe/
│   ├── models.py             # ProxyConfig, TestResult dataclasses
│   ├── fetcher.py            # Fetch & base64-decode subscription URLs
│   ├── parser.py             # Parse config URLs → ProxyConfig
│   ├── runners/
│   │   ├── base.py           # ProxyRunner ABC (context manager)
│   │   ├── xray.py           # XrayProcess — vless/vmess/ss/trojan
│   │   └── hysteria2.py      # Hysteria2Process
│   ├── tester.py             # Per-config test + safety checks + geo enrichment
│   ├── safety.py             # SafetyCheck ABC + DNS/IPv6/TLS/integrity checks
│   ├── reporter.py           # CSV/JSON output + terminal summary
│   └── config.py             # Constants (timeouts, binary paths)
└── scripts/
    ├── orchestrate.py        # Parallel Docker container orchestration
    └── merge_results.py      # Merge shard outputs into one CSV/JSON
```

**Pipeline per run:**

1. Fetch subscription URLs → decode base64 → split into raw config lines
2. Parse each line into a `ProxyConfig` (protocol, server, port, params)
3. Deduplicate — exact string match, then credential-level (`protocol|server|port|auth`)
4. *(If sharded)* Each container receives its 1/N slice via `--shard I --shards N`
5. Per config: TCP pre-check → launch xray or hysteria2 subprocess → `curl` through local SOCKS5 → run safety checks
6. Batch geo-IP enrichment via ip-api.com after all tests complete
7. *(If sharded)* `merge_results.py` concatenates shard CSVs/JSONs into `merged/`

## Safety Checks per Config

| # | Check | Output field | What it means |
| - | ----- | ------------ | -------------- |
| 1 | **Traffic redirection** — exit IP compared to local IP | `is_redirecting` | `false` = broken or leaking proxy; zero anonymity |
| 2 | **Encryption layer** — `security` param parsed from the config URL | `protocol`, params | `none` = plaintext tunnel; `tls`/`reality` = encrypted |
| 3 | **Datacenter vs. residential** — ip-api.com `hosting` flag | `is_datacenter` | `false` on a public config may indicate a botnet relay |
| 4 | **Blacklist / reputation** — ip-api.com `proxy` flag on exit IP | `is_blacklisted` | `true` = IP is a known proxy, VPN, or Tor exit node |
| 5 | **DNS leak** — bash.ws DNS leak test triggered through the proxy | `dns_leak` | `true` = DNS resolver matches local network, not the proxy |
| 6 | **IPv6 leak** — `curl -6` through the proxy compared to local IPv6 | `ipv6_leak` | `true` = real IPv6 address exposed despite proxy |
| 7 | **TLS fingerprint / MITM** — cert SHA-256 direct vs. through proxy | `tls_tampered` | `true` = certificate mismatch, active interception suspected |
| 8 | **Response integrity** — two independent IP-check services cross-verified | `response_tampered` | `true` = services disagree or exit IP inconsistent |
| 9 | **Geo-IP** — country, city, org, ASN resolved for every working exit IP | `country`, `city`, `org`, `asn` | Mismatch between claimed and actual region is a warning sign |
| 10 | **Latency** — round-trip time through the proxy to the IP-check endpoint | `latency_ms` | < 50 ms to a distant server may indicate traffic stays local |

See [SAFETY.md](SAFETY.md) for the full threat model and interpretation guide.
