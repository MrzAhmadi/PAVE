# Safety Assessment Methodology

This document describes how the VPN Config Checker evaluates whether a free VPN
configuration is safe to use.

---

## 1. Threat Model

Free VPN configurations shared publicly carry two categories of risk:

### 1.1 Traffic Interception
The operator of the server controls the exit node. Any traffic that is **not
end-to-end encrypted** (e.g. plain HTTP, unencrypted DNS) can be read, logged,
or modified by the server operator. A malicious operator could:

- Log all visited domains and IP addresses
- Steal credentials submitted over plain HTTP
- Inject advertisements or malware into HTTP responses
- Sell browsing history to third parties

### 1.2 Identity / Metadata Exposure
Some free configs are published intentionally as **honeypots** to collect the
real IP addresses and usage patterns of people who connect to them. Connecting
to such a server reveals:

- Your real IP address (exposed at connection time, before any traffic flows)
- Your connection timestamp and frequency
- The fact that you are using a proxy or VPN tool

---

## 2. What This Tool Checks Automatically

For every configuration tested, the tool records the following signals.
All fields appear as columns in the output CSV.

### 2.1 Traffic Redirection (`is_redirecting`)
**How:** After connecting through the proxy, the tool fetches `https://api.ipify.org`
and compares the returned IP to the local (real) IP address detected before any
proxy is used.

```
is_redirecting = (exit_ip != local_ip)
```

**What it means:**
- `True` — traffic is leaving through a different IP; the proxy is functioning.
- `False` — the exit IP matches the local IP, meaning the proxy is broken,
  non-functional, or actively routing traffic back to the user. **Do not use.**

A config that is not redirecting provides zero anonymity benefit and may still
expose the user's intent to connect to a proxy server.

### 2.2 Encryption Layer (`protocol` + `security` parameter)
**How:** Parsed directly from the config URL during the parsing stage. The
`security` field in the config params records the transport security type.

| Value | Meaning |
|---|---|
| `tls` | Standard TLS 1.2/1.3 — encrypted tunnel to the server |
| `reality` | XTLS Reality — TLS camouflaged as normal HTTPS traffic |
| `none` | **No encryption** — traffic between client and server is plaintext |

**What it means:**  
Configs with `security=none` expose all traffic to anyone on the network path
between the user and the server (ISP, router, any intermediate hop). The server
operator can also read everything. These configs should be considered **unsafe**
for any sensitive activity.

Configs using `tls` or `reality` encrypt the tunnel, so intermediate observers
cannot read the content — though the server operator still can.

### 2.3 Exit IP Geolocation (`country`, `city`, `org`, `asn`)
**How:** After a successful connection, the exit IP is looked up using the
`ip-api.com` API, which returns country, city, ISP name, and ASN.

**What it means:**  
- Identifies where your traffic appears to originate from.
- Useful for verifying that the config actually routes through the claimed region.
- A mismatch between the server hostname/label and the actual exit country is a
  warning sign that the config may be misconfigured or misleading.

### 2.4 Datacenter vs. Residential IP (`is_datacenter`)
**How:** The `hosting` field returned by `ip-api.com` indicates whether the exit
IP belongs to a hosting provider, cloud platform, or datacenter.

**What it means:**
- `True` — the exit IP is from a datacenter or cloud provider (AWS, Hetzner,
  CDN77, etc.). This is **expected and normal** for legitimate VPN services.
- `False` — the exit IP appears to be a residential or business ISP address.
  This is unusual for a public VPN config and could indicate:
  - A compromised residential machine being used as an exit node (botnet relay)
  - A deliberately deceptive server designed to look residential

### 2.5 Latency (`latency_ms`)
**How:** Measured as the round-trip time from sending the request through the
SOCKS5 proxy to receiving the exit IP response.

**What it means:**  
Latency alone is not a safety signal, but extreme outliers are worth noting:

- **Very low latency to a geographically distant server** (e.g. < 50 ms to a
  server listed as being in Asia from Europe) may indicate the exit IP is not
  where it claims to be, or that the request is not actually leaving the local
  network.
- **Very high latency** (> 5000 ms) suggests the server is overloaded or the
  route is unstable — not a safety issue, but the config is impractical.

---

## 3. Safety Classification (Summary Table)

Based on the signals above, each config can be informally classified as follows:

| Condition | Safety Implication |
|---|---|
| `is_redirecting = False` | **Non-functional** — zero anonymity |
| `security = none` | **Unsafe** — all traffic visible to server operator and network path |
| `security = tls` or `reality` | Tunnel is encrypted — safer |
| `is_datacenter = True` | Normal for VPN infrastructure |
| `is_datacenter = False` | Unusual — possible botnet/residential relay |
| `latency_ms < 50` to distant server | Suspicious — verify exit location |
| `exit_ip != server address` (CDN relay) | Neutral — common with CDN-fronted configs |

---

## 4. What This Tool Does NOT Check

These limitations are important to understand, especially in a research context:

### 4.1 Server Operator Trustworthiness
Even a fully encrypted, correctly redirecting config does not guarantee the
server operator is honest. The operator can always see:
- Which IP addresses connect and when
- The destination IPs of all traffic (even through TLS, the server sees where
  it forwards your packets)
- Unencrypted DNS queries if DNS is resolved server-side without DoH/DoT

There is no automated way to verify operator intent from the outside.

### 4.2 DNS Leak Detection *(planned)*
A DNS leak occurs when DNS queries bypass the VPN tunnel and are sent directly
to the user's local DNS resolver, revealing browsing intent to the ISP.

Detection approach (not yet implemented):
```
while connected through the VPN:
    query a DNS-leak test API (e.g. bash.ws/dnsleak) through the proxy
    if the returned DNS resolver IP != exit_ip:
        dns_leak = True
```

### 4.3 Traffic Injection / MITM
Detecting whether a server is actively injecting content into HTTP responses
would require fetching a known resource and comparing the hash — not yet
implemented.

### 4.4 Honeypot / Logging Intent
Whether a server is intentionally collecting data cannot be determined
programmatically. This is a known limitation of any automated tool that tests
publicly shared VPN configs.

---

## 5. Recommended Interpretation for Research

When analyzing the output CSV for a paper or report:

1. **Filter `is_redirecting = True`** as the baseline "working" set.
2. **Within the working set, flag `security = none`** as the high-risk subset.
3. **Use `is_datacenter`** to separate professional infrastructure from
   anomalous residential exits.
4. **Use `country_code` and `org`** to map the geographic and organizational
   distribution of exit nodes.
5. **Treat latency** as a quality-of-service metric, not a safety metric.

A config can be considered **functionally safe** (for the purposes of this
tool's automated assessment) if all of the following are true:

```
is_redirecting  = True
security        = tls  OR  reality
is_datacenter   = True   (expected infrastructure)
latency_ms      < 5000
```

This does not guarantee the server operator is trustworthy — it only means the
config behaves as a correctly functioning, encrypted proxy.
