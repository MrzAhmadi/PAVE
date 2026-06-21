# PAVE — Proxy Analysis and Verification Engine

Fetches free proxy/VPN subscription URLs, deduplicates configs, and tests each one for reachability.
Supports vless, vmess, shadowsocks, ShadowsocksR, trojan, hysteria2, TUIC, and SOCKS.
Results are exported as CSV/JSON with geo-IP enrichment (country, city, ASN, datacenter flag).

**Requires Docker** (the proxy binaries run inside containers).

---

## Installation

### Debian / Ubuntu

```bash
wget https://github.com/MrzAhmadi/PAVE/releases/latest/download/pave_latest_all.deb
sudo apt install ./pave_latest_all.deb
pave --help
```

### RHEL / Fedora / CentOS

```bash
wget https://github.com/MrzAhmadi/PAVE/releases/latest/download/pave-latest.noarch.rpm
sudo rpm -i pave-latest.noarch.rpm
pave --help
```

### Any Linux (.tar.gz)

```bash
wget https://github.com/MrzAhmadi/PAVE/releases/latest/download/pave-latest-linux.tar.gz
tar -xzf pave-latest-linux.tar.gz
cd pave-*/
sudo ./install.sh
pave --help
```

> Find exact filenames on the [Releases page](https://github.com/MrzAhmadi/PAVE/releases/latest).

---

## Usage

### `pave run` — run an experiment

```bash
pave run -s subscriptions.txt
```

On first run it builds the Docker image, fetches and deduplicates all subscription configs, distributes work across N parallel containers, then merges the results.

```text
pave run -s FILE [options]

required:
  -s, --subs FILE          Subscriptions file (one URL per line, # = comment)

scale:
  -n, --containers N       Parallel Docker containers          (default: 12)
  -w, --workers N          Concurrent workers per container    (default: 50)

output:
  -o, --outdir DIR         Results directory                   (default: results/YYYY-MM-DD_HH-MM)
  -f, --format FORMAT      csv | json | both                   (default: both)
  -l, --limit N            Max configs per shard (smoke test)

timeouts:
  --timeout SEC            curl connection timeout             (default: 15)
  --tcp-timeout SEC        TCP reachability pre-check          (default: 2)
  --startup-timeout SEC    Proxy binary startup timeout        (default: 3)

behaviour:
  --progress-interval N    Log summary every N configs         (default: 250)
  --no-build               Skip Docker image rebuild
  -v, --verbose            DEBUG-level logging inside containers
```

**Examples:**

```bash
# Standard run — 20 containers
pave run -s subscriptions.txt -n 20

# Smoke test — fast check with 50 configs per shard
pave run -s subscriptions.txt -n 2 -l 50 -w 10

# Tune timeouts to reduce errors
pave run -s subscriptions.txt -n 20 --timeout 20 --tcp-timeout 3

# Skip rebuild after a code change
pave run -s subscriptions.txt -n 20 --no-build -o results/run-02
```

Output directory layout after a run:

```text
results/2024-01-01_12-00/
├── results.csv     ← merged results (all shards combined)
├── results.json    ← same data as JSON
└── logs/
    ├── fetch.log
    ├── shard_0.log
    └── shard_N.log
```

---

### `pave serve` — explore results in the browser

```bash
pave serve -r results/2024-01-01_12-00
```

Starts a local web dashboard, loads your results CSV automatically, and opens the browser.

```text
pave serve [options]

  -r, --results DIR    Results directory to load
  -p, --port PORT      Port to listen on (default: 8000)
  --no-browser         Do not open browser automatically
```

---

### `pave version` — show version info

```bash
pave version
```

```text
pave        0.1.0
python      3.11.0
docker      24.0.5, build ...
```

---

## Releases (GitHub Actions)

Every `v*.*.*` tag triggers a build that publishes to:

| Target | Format | How to install |
| --- | --- | --- |
| **PyPI** | `.whl` | `pip install pave-proxy` |
| **Debian/Ubuntu** | `.deb` | `apt install ./pave_*.deb` |
| **RHEL/Fedora** | `.rpm` | `rpm -i pave-*.rpm` |
| **Any Linux** | `.tar.gz` | `sudo ./install.sh` |

To cut a release:

```bash
git tag v0.2.0
git push origin v0.2.0
```

### PyPI setup (one-time)

PAVE uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no API token needed:

1. Create the project on [pypi.org](https://pypi.org)
2. Go to **Publishing** → **Add a new pending publisher**
3. Fill in: owner `MrzAhmadi`, repository `PAVE`, workflow `release.yml`, environment `pypi`
4. In GitHub → Settings → Environments → create `pypi`

After that, `git push v*.*.*` does the full release automatically.

---

## Output Fields

### Connection

| Field | Description |
| --- | --- |
| `config_id` | MD5 hash of the raw config string (12 chars) |
| `raw_config` | Original proxy URI (e.g. `vmess://…`) |
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

### Geo

| Field | Description |
| --- | --- |
| `country` | Exit IP country name |
| `country_code` | ISO 3166-1 alpha-2 code |
| `city` | Exit IP city |
| `org` | ISP / hosting company name |
| `asn` | Autonomous System Number |
| `is_datacenter` | `true` if exit IP belongs to a hosting/datacenter range |
| `is_blacklisted` | `true` if exit IP is flagged as a known proxy |

### Security checks

| Field | Description |
| --- | --- |
| `dns_resolver_ip` | IP of the DNS resolver used through the proxy |
| `dns_resolver_country` | Country of that DNS resolver |
| `dns_leak` | `true` if DNS resolver country differs from exit IP country |
| `ipv6_exit_ip` | IPv6 address returned when connecting through the proxy |
| `ipv6_leak` | `true` if IPv6 exit country differs from IPv4 exit country |
| `proxy_detected` | `true` if exit IP is detected as a proxy by ip-api.com |
| `x_forwarded_for` | `X-Forwarded-For` header value (reveals origin IP if present) |
