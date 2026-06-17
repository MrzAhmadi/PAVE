# ConfigProbe

Fetches free proxy/VPN subscription URLs, deduplicates configs, and tests each one for reachability and IP redirection.
Supports vless, vmess, shadowsocks, trojan, hysteria2, SSR, SOCKS, and TUIC protocols.
Results are exported as CSV/JSON with geo-IP enrichment (country, city, ASN, datacenter flag).

## How to Run

### 1. Add subscription URLs

Create `subscriptions.txt` (one URL per line):

```
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

```
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

## Safety Checks per Config

| Check | Output field | What it means |
| ----- | ------------ | -------------- |
| **Traffic redirection** — exit IP is compared to the local IP before any proxy is used | `is_redirecting` | `false` = proxy is broken or leaking; provides zero anonymity |
| **Encryption layer** — `security` param parsed from the config URL | `protocol`, params | `none` = plaintext tunnel; `tls`/`reality` = encrypted |
| **Datacenter vs. residential** — exit IP classified via ip-api.com `hosting` flag | `is_datacenter` | `false` on a public config is unusual and may indicate a botnet relay |
| **Geo-IP** — country, city, org, and ASN resolved for every working exit IP | `country`, `city`, `org`, `asn` | Mismatch between claimed and actual region is a warning sign |
| **Latency** — round-trip time through the proxy to the IP-check endpoint | `latency_ms` | < 50 ms to a distant server may indicate traffic is not leaving the local network |

See [SAFETY.md](SAFETY.md) for the full threat model and interpretation guide.
