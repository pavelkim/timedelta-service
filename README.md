# Timedelta Service

A quick way to compare clocks between your servers.

## Exporter

```
=== TimeDelta Exporter  |  2026-02-12 03:21:17 CET ===

  Host: 2d1577a13ac4
    Neighbour             Dead  Syncs    Clock Δ (last)    Clock Δ (mean)    RTT (last)    RTT (mean)
    ─────────────────────────────────────────────────────────────────────────────────────────────────
    084cb9884c56          DEAD      –                 –                 –             –             –
    0cd30a620414          DEAD      –                 –                 –             –             –
    6276f7f74275          DEAD      –                 –                 –             –             –
    af085a932247          DEAD      –                 –                 –             –             –
    ginger                  ok     17         -1.469925         -1.427447      0.776184      0.737536
    laptop-local            ok     17         -0.011882         -0.031112      1.307451      1.180117
    trixie                  ok     18         -0.261688         -0.260921      0.958644      0.868325

  Host: ginger
    Neighbour             Dead  Syncs    Clock Δ (last)    Clock Δ (mean)    RTT (last)    RTT (mean)
    ─────────────────────────────────────────────────────────────────────────────────────────────────
    084cb9884c56          DEAD      –                 –                 –             –             –
    0cd30a620414          DEAD      –                 –                 –             –             –
    2d1577a13ac4            ok     16         +1.253867         +1.256548      0.406100      0.424577
    6276f7f74275          DEAD      –                 –                 –             –             –
    af085a932247          DEAD      –                 –                 –             –             –
    laptop-local            ok     16         +1.268306         +1.243314      0.375958      0.374465
    trixie                  ok     16         +1.193156         +1.185808      0.133299      0.126673

  Host: laptop-local
    Neighbour             Dead  Syncs    Clock Δ (last)    Clock Δ (mean)    RTT (last)    RTT (mean)
    ─────────────────────────────────────────────────────────────────────────────────────────────────
    084cb9884c56          DEAD      –                 –                 –             –             –
    0cd30a620414          DEAD      –                 –                 –             –             –
    2d1577a13ac4            ok     16         -0.268757         -0.206228      1.238955      0.970567
    6276f7f74275          DEAD      –                 –                 –             –             –
    af085a932247          DEAD     85         -0.136749         -0.135326      0.805551      0.708027
    ginger                  ok    205         -1.224842         -1.232949      0.415384      0.369481
    trixie                  ok    193         -0.091415         -0.120468      0.526906      0.506582

  Host: trixie
    Neighbour             Dead  Syncs    Clock Δ (last)    Clock Δ (mean)    RTT (last)    RTT (mean)
    ─────────────────────────────────────────────────────────────────────────────────────────────────
    084cb9884c56          DEAD      –                 –                 –             –             –
    0cd30a620414          DEAD      –                 –                 –             –             –
    2d1577a13ac4            ok     18         -0.067223         -0.038465      0.181893      0.223458
    6276f7f74275          DEAD      –                 –                 –             –             –
    af085a932247          DEAD      –                 –                 –             –             –
    ginger                  ok     25         -1.171784         -1.173408      0.089296      0.101610
    laptop-local            ok     33         -0.066224         -0.039094      0.136033      0.193806

  (4 host(s) reporting)

```

## Support

Gituhb issues: https://github.com/pavelkim/timedelta-service/issues

