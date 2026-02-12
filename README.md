# Timedelta Service

A quick way to compare clocks between your servers.

## How It Works

The service uses a time synchronization algorithm similar to NTP to measure clock differences between hosts. Each measurement consists of four timestamps to calculate:
- **Clock Delta (Δ)**: The offset between the remote and local clock
- **RTT (Round-Trip Time)**: The network delay for the measurement

## Exporter

Dev: http://127.0.0.1:18220/tdsvc_exporter

The exporter displays clock delta statistics with RTT-based filtering:

```
=== TimeDelta Exporter  |  2026-02-12 14:52:03 UTC ===

  Host: dev-docker-1
    Neighbour             Dead  Syncs        Δ (best)        Δ (filt)         Δ (raw)    RTT (last)    RTT (best)
    ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    dev-docker-2            ok     20       +0.999364       +0.998270       +0.998241      7.005943      7.003631
    dev-docker-3            ok     20       +0.999414       +0.999482       +0.999414      8.005248      8.005248

  Host: dev-docker-2
    Neighbour             Dead  Syncs        Δ (best)        Δ (filt)         Δ (raw)    RTT (last)    RTT (best)
    ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    dev-docker-1            ok     20       +0.999152       +0.998768       +0.999194      7.004374      7.004147
    dev-docker-3            ok     20       +0.998462       +0.999001       +0.997917      8.006615      8.004828

  Host: dev-docker-3
    Neighbour             Dead  Syncs        Δ (best)        Δ (filt)         Δ (raw)    RTT (last)    RTT (best)
    ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    dev-docker-1            ok     20       +0.999025       +0.999102       +0.997467      7.009017      7.002918
    dev-docker-2            ok     20       +0.999343       +0.999086       +0.998220      7.006397      7.002425

  (3 host(s) reporting)
```


## Support

Gituhb issues: https://github.com/pavelkim/timedelta-service/issues

