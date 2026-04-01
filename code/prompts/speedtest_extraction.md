---
version: "2.0"
# model and temperature are set at runtime from config.yaml — values here are for reference only
temperature: 0.15
output_format: json
accuracy_target: 0.90
---

Extract speed test results from this Ookla Speedtest screenshot.

## Layout Guide

The Ookla Speedtest results screen has this layout:

- **DOWNLOAD Mbps** — large number on the left (e.g. 68.9, 598, 773)
- **UPLOAD Mbps** — large number on the right (e.g. 18.3, 79.1, 77.5)
- **PING ms** section below with three columns:
  - Idle (leftmost number)
  - Download (middle number)
  - Upload (rightmost number)
- **Jitter** — small number below each ping column
- **Packet Loss %** — number at the bottom (e.g. 0.0)

## Reading Rules

- DL is ALWAYS the left/first large number, UL is ALWAYS the right/second
- Read the EXACT number shown — do not round
- DL range: 0 to 3000 Mbps
- UL range: 0 to 500 Mbps
- Ping range: 1 to 1000 ms
- If "RESULTS" header is visible at top, these are final results

## Output JSON

{
  "screenshot_type": "speedtest",
  "dl_throughput_mbps": null,
  "ul_throughput_mbps": null,
  "ping_idle_ms": null,
  "ping_dl_ms": null,
  "ping_ul_ms": null,
  "jitter_ms": null,
  "packet_loss_pct": null,
  "server_name": null,
  "isp": null,
  "timestamp": null,
  "confidence": 0.9
}

Return ONLY the JSON. No explanation. Start with { and end with }.

/no_think
