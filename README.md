# ConfigProbe

Fetches free proxy/VPN subscription URLs, deduplicates configs, and tests each one for reachability.
Supports vless, vmess, shadowsocks (SS), ShadowsocksR (SSR), trojan, hysteria2, TUIC, and SOCKS protocols.
Results are exported as CSV/JSON with geo-IP enrichment (country, city, ASN, datacenter flag).

## How to Run

### 1. Add subscription URLs

Edit `src/subscriptions.txt` — one URL per line, `#` lines are comments:

```text
https://example.com/sub1
https://example.com/sub2
```

### 2. Parallel containers (recommended)

Run from the `src/` directory. This fetches once, splits work across N containers, and merges results:

```bash
cd src
python scripts/orchestrate.py 12 --outdir ../results
```

Smoke test (100 configs per shard):

```bash
python scripts/orchestrate.py 2 100 --workers 10 --outdir ../results
```

Options:

```text
python scripts/orchestrate.py [containers] [limit_per_shard]
  --workers N            Concurrent workers per container (default: 50)
  --outdir PATH          Output directory (default: config_results)
  --progress-interval N  Log summary every N configs per container (default: 250)
```

Results are written to `results/merged/results.csv` and `results/merged/results.json`.

### 3. Single container

```bash
cd src
docker compose run --rm configprobe \
  -i /subs/subscriptions.txt \
  -w 10 \
  -o /results \
  -f both
```

### 4. Rebuild the image

Required after any code change or when updating the base binaries (xray, hysteria2, sing-box):

```bash
cd src
docker compose build
```

## Output Fields

### Connection

| Field | Description |
| --- | --- |
| `config_id` | MD5 hash of the raw config string (12 chars) |
| `protocol` | vless / vmess / ss / ssr / trojan / hysteria2 / tuic / socks |
| `server` | Remote server hostname or IP |
| `port` | Remote port |
| `name` | Config display name from the subscription |
| `source` | Subscription URL the config came from |
| `timestamp` | UTC time the test was run |
| `success` | Whether a connection was established |
| `latency_ms` | Round-trip time through the proxy (ms) |
| `exit_ip` | Public IP seen at the exit node |
| `local_ip` | Public IP of the test machine |
| `is_redirecting` | `true` if exit IP differs from local IP |
| `error` | Error message if the test failed |

### Geo (enriched after all tests via ip-api.com batch API)

| Field | Description |
| --- | --- |
| `country` | Exit IP country name |
| `country_code` | ISO 3166-1 alpha-2 code |
| `city` | Exit IP city |
| `org` | ISP / hosting company name |
| `asn` | Autonomous System Number |
| `is_datacenter` | `true` if exit IP belongs to a hosting/datacenter range |
| `is_blacklisted` | `true` if exit IP is flagged as a known proxy by ip-api.com |

### Security checks (run through the proxy while it is alive)

| Field | Description |
| --- | --- |
| `dns_resolver_ip` | IP of the DNS resolver used through the proxy |
| `dns_resolver_country` | Country of that DNS resolver |
| `dns_leak` | `true` if DNS resolver country differs from exit IP country |
| `ipv6_exit_ip` | IPv6 address returned when connecting through the proxy |
| `ipv6_leak` | `true` if IPv6 exit country differs from IPv4 exit country |
| `proxy_detected` | `true` if the exit IP is detected as a proxy by ip-api.com (queried from inside the proxy) |
| `x_forwarded_for` | Value of `X-Forwarded-For` header injected by the proxy (reveals origin IP if present) |

## Architecture

```text
src/
├── main.py                          # CLI entrypoint
├── subscriptions.txt                # Subscription URLs (one per line)
├── configprobe/
│   ├── config.py                    # Constants (timeouts, paths, worker count)
│   ├── models.py                    # ProxyConfig, TestResult dataclasses
│   ├── fetcher.py                   # Fetch & base64-decode subscription URLs
│   ├── parser.py                    # Parse raw URI strings → ProxyConfig
│   ├── checks.py                    # ProxyCheck ABC + DNS / IPv6 / header / detection checks
│   ├── tester.py                    # Orchestration: run_tests(), _enrich_geo()
│   ├── reporter.py                  # CSV/JSON writer + terminal summary
│   ├── protocols/                   # One file per protocol — OOP, all inherit ProtocolTester
│   │   ├── base.py                  # ProtocolTester ABC, XrayBasedTester, SingboxBasedTester
│   │   ├── vless.py                 # VlessProtocolTester
│   │   ├── vmess.py                 # VmessProtocolTester
│   │   ├── shadowsocks.py           # ShadowsocksProtocolTester
│   │   ├── shadowsocksr.py          # ShadowsocksRProtocolTester
│   │   ├── trojan.py                # TrojanProtocolTester
│   │   ├── hysteria2.py             # Hysteria2ProtocolTester
│   │   ├── tuic.py                  # TuicProtocolTester
│   │   ├── socks.py                 # SocksProtocolTester
│   │   └── __init__.py              # create_tester() factory
│   └── runners/                     # Subprocess lifecycle managers (context managers)
│       ├── base.py                  # ProxyRunner ABC
│       ├── xray.py                  # XrayProcess — vless / vmess / ss / trojan
│       ├── hysteria2.py             # Hysteria2Process
│       └── singbox.py               # SingboxProcess — tuic / ssr
└── scripts/
    ├── orchestrate.py               # Parallel Docker orchestration
    └── merge_results.py             # Merge per-shard outputs into one file
```

### Class hierarchy

```text
ProtocolTester (ABC)  ←  checks.py / ProxyCheck (ABC)
├── XrayBasedTester        ├── DnsCheck
│   ├── VlessProtocolTester     ├── IPv6LeakCheck
│   ├── VmessProtocolTester     ├── ProxyDetectionCheck
│   ├── ShadowsocksProtocolTester└── HeaderLeakCheck
│   └── TrojanProtocolTester
├── SingboxBasedTester
│   ├── TuicProtocolTester
│   └── ShadowsocksRProtocolTester
├── Hysteria2ProtocolTester
└── SocksProtocolTester

runners/
ProxyRunner (ABC)
├── XrayProcess
├── Hysteria2Process
└── SingboxProcess
```

### Pipeline

1. Fetch subscription URLs → decode base64 → split into raw config lines
2. Parse each line into a `ProxyConfig` (protocol, server, port, params)
3. Deduplicate — exact string match, then credential-level (`protocol|server|port|auth`)
4. *(Sharded)* Each container receives its 1/N slice via `--shard I --shards N`
5. Per config — `create_tester()` selects the right `ProtocolTester`:
   - TCP pre-check (IP targets only)
   - Launch proxy subprocess via the matching runner (`XrayProcess` / `Hysteria2Process` / `SingboxProcess`)
   - `curl` through the local SOCKS5 port → get `exit_ip` and `latency_ms`
   - If connected: run all 4 `ProxyCheck`s **in parallel** through the same proxy port
   - Proxy subprocess terminates
6. Batch geo-IP enrichment via ip-api.com after all tests complete
7. Compute `dns_leak` (DNS country ≠ exit country) and `ipv6_leak` (IPv6 exit country ≠ IPv4 exit country)
8. *(Sharded)* `merge_results.py` concatenates shard outputs into `merged/`
