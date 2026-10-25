# eBPF flow exporter (v2 scaffold)

Optional DaemonSet design for socket-level egress telemetry without paid VPC flow-log ingestion.

This directory documents the contract only. No kernel module or eBPF program ships in v1.7.x.

## Intended deployment

- Run one pod per node with `hostNetwork: false` and a restricted `CAP_BPF` capability set.
- Export aggregated byte counters to the CloudSaver collector over mTLS on `127.0.0.1`.

## Out of scope

- Building or distributing eBPF bytecode in CI
- Privileged `hostPID` collectors
