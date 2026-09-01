# Water-Level OrangePi Payload

This directory is the self-contained OrangePi-side payload for the pTLC
water-level service. Copy the whole directory to the configured remote
`water_level.work_dir` and start it with:

```bash
bash run.sh
```

The upper-computer driver still talks to the service through MQTT and MJPEG.
Keeping these scripts under `eit_ptlc/driver` makes the application portable
without relying on a separate repository checkout.
