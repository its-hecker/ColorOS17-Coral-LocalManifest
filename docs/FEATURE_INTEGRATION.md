# Existing floral feature integrations

All versions are pinned in `sources.lock.json`.

### GCam: floral-gcam-plugin

Stock Google Camera 8.7 APK-set integration needs actual Google camera HAL/Airbrush runtime, prebuilt split APKs and SELinux labels. The plugin's `gcam.mk` is an AOSP product makefile and cannot be consumed by a binary ColorOS GSI without an adaptation pipeline.

### Face: floral-3D-faceid-plugin

Pinned Android 17 version includes native HAL compatibility, Citadel keymaster, secure calibration, platform framework fixes and overlays. A ColorOS system may not contain the AOSP methods to which these source patches apply. Inspect `services.jar` / system biometric stack and implement only reviewed binder-interface adaptations. Retain real hardware-backed authentication.

### Soli: floral-motionsense-plugin

Motion Sense includes an Oslo/CHRE bridge, overlay and application. Its stock AOSP SystemUI plugin hooks may be absent/modified in ColorOS. Preserve vendor firmware/calibration and test runtime plugin loading; do not report Motion Sense working based only on the settings app appearing.

### Test order

Prioritize genuine ColorOS first boot before applying all three features. Preserve existing camera provider, Citadel and CHRE dependencies through every system build; then enable GCam, Face and Soli individually to isolate crashes.
