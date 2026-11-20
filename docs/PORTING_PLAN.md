# Plan and engineering gates

## Stage 0: reproducible input audit (this branch)

- Pin exact HeckerOS coral hardware sources, kernel source, three Android 17 Floral plugins and a community port reference.
- Select the PLK110 Axis GSI donor; stream-download it locally and record SHA-256.
- Inspect archive topology and image formats; determine system/product/system_ext and any ColorOS `my_*` dependencies before writing unpack/repack code.
- Check Pixel vendor prerequisites and kernel version. Fail fast on missing hardware inputs.

**Exit condition:** exact source revisions checked out, donor ZIP inspectable, detected supported image formats, audited hardware interfaces, no donor trust conflicts. This does not establish bootability.

## Stage 1: system adaptation

- Document actual GSI partition mapping and implement **repeatable** unpack, patch and repack transforms for the detected format. Preserve hash and licensing provenance.
- Review ColorOS init, VINTF, binder services, property contexts, hardware composer and SELinux compatibility with Pixel vendor. Avoid persistent permissive SELinux as a substitute for correct policy.
- Prepare a coral-specific boot chain using the known floral kernel and stock device configuration. Verify ramdisk, fs_mgr, encryption, rollback and partition size requirements.

## Stage 2: boot and essentials

- First meaningful milestone: SurfaceFlinger/SystemUI loads, screen/touch works, userdata decrypts securely.
- Restore audio, radio/IMS, Wi-Fi, Bluetooth, sensors, charging and camera. Compare real logs against each patch.

## Stage 3: Pixel-exclusive features

- GCam: repackage original signed APK set, retain Google's camera HAL/privileges. Check camera and Face ID co-use.
- Face ID: integrate the real Pixel IR/Citadel biometric provider with ColorOS system framework and settings. Use guarded adapters; never use fake authentication success.
- Soli: preserve CHRE/Oslo firmware and verify bridge and SystemUI hooks using ColorOS's actual interfaces (AOSP plugin assumptions are invalid until proven).

## Stage 4: security, stability, recovery

- Prove encryption, verified boot choices, restrictive SELinux, OTA compatibility and rollback path; perform long-running radio, camera, suspend/resume and biometric tests.
- Only provide a flashable package once device-specific tests and backups/rollback steps exist.

## Deliberately out of scope for Stage 0

No first-boot claim, no downloadable ROM ZIP, no flashing procedure, no proprietary firmware uploads and no guarantee every OPPO feature is compatible.
