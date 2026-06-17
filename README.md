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
| `country` | Exit IP country |
| `country_code` | ISO 3166-1 alpha-2 country code |
| `city` | Exit IP city |
| `org` | Exit IP organisation / ISP |
| `asn` | Exit IP autonomous system number |
| `is_datacenter` | `true` if exit IP is a known hosting/datacenter range |
| `is_blacklisted` | `true` if exit IP is flagged as a known proxy/VPN by ip-api.com |
| `error` | Error message if the test failed |

## Architecture

```text
src/
├── main.py                    # CLI entrypoint
├── subscriptions.txt          # Subscription URLs (one per line)
├── configprobe/
│   ├── models.py              # ProxyConfig, TestResult dataclasses
│   ├── fetcher.py             # Fetch & decode subscription URLs
│   ├── parser.py              # Parse raw config strings → ProxyConfig
│   ├── tester.py              # Connection testing + geo enrichment
│   ├── reporter.py            # CSV/JSON output + terminal summary
│   ├── config.py              # Constants (timeouts, binary paths)
│   └── runners/
│       ├── base.py            # ProxyRunner ABC
│       ├── xray.py            # vless / vmess / ss / trojan (via Xray-core)
│       ├── hysteria2.py       # hysteria2 (via hysteria2 binary)
│       └── singbox.py         # tuic / ssr (via sing-box)
└── scripts/
    ├── orchestrate.py         # Parallel Docker orchestration
    └── merge_results.py       # Merge shard outputs into one file
```

**Pipeline:**

1. Fetch subscription URLs → decode base64 → split into raw config lines
2. Parse each line into a `ProxyConfig` (protocol, server, port, params)
3. Deduplicate — exact string match, then credential-level (`protocol|server|port|auth`)
4. *(Sharded)* Each container receives its 1/N slice via `--shard I --shards N`
5. Per config: TCP pre-check → launch proxy subprocess (xray / hysteria2 / sing-box) → `curl` through local SOCKS5 port
6. Batch geo-IP enrichment via ip-api.com after all tests complete
7. *(Sharded)* `merge_results.py` concatenates shard outputs into `merged/`
