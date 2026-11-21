# ColorOS 17 for Pixel 4 XL — one-command experimental engineering build

The new `build.sh` produces an **experimental first-boot image archive** using the real PLK110 ColorOS 17 system, the known Android 17 coral hardware source and the compiled Pixel vendor/kernel. It is **not a verified working ROM or OTA**; runtime VINTF, SELinux, hardware biometrics and Soli integration still require on-phone logs and iteration.

## Run on ServerHive / Ubuntu

```bash
git clone -b dev/coloros17-firstboot https://github.com/its-hecker/ColorOS17-Coral-LocalManifest.git ~/coloros17-coral-port
cd ~/coloros17-coral-port
USE_RBE=true bash build.sh
```

The command uses a separate Android source tree (`~/coloros17-coral/aosp`) so your HeckerOS checkout and upstream GitHub repositories remain untouched. It builds HeckerOS's Android 17 coral hardware with the first-stage fstab adapted for the donor's **embedded product/system_ext directories**, then validates vendor image size and stages ColorOS.

If all safety checks pass, the `tools/build_firstboot_images.py` program:

- Starts from the SHA-pinned PLK110 raw ext4 `system.img`, never modifying the downloaded original.
- Mounts compiled Pixel product/system_ext images read-only and transplants strictly selected Google Camera, IMS, RIL and Soli APK/framework files, preserving ext4 SELinux labels; it refuses donor package overwrites.
- Reconciles only exact nonplatform property-context collisions with the Pixel vendor, retaining inode labels; unresolved collisions stop the build.
- Generates a cryptographically signed system AVB hashtree and `vbmeta_system.img` with the same signing key as the baseline root `vbmeta.img` (checks trusted chain key and rollback location; refuses verification-disabled root metadata).
- Calculates the actual dynamic group budget and constructs a sparse A/B `super.img` from the original build's real `META/misc_info.txt` parameters, with ColorOS system + Pixel vendor (no duplicated product/system_ext).
- Packages `super.img`, `boot.img`, `dtbo.img`, `vbmeta.img` and `vbmeta_system.img` into an `FIRSTBOOT-UNTESTED-images.zip` engineering archive.

## Important limitations

**This is not a recovery/sideload installer, no boot success is claimed, and the ZIP must not be flashed without a verified device-specific installation and rollback procedure.** The actual ColorOS framework is compiled by OPPO and cannot be rebuilt as part of HeckerOS; our pipeline adapts its binary system image. On-device boot logs and Android framework integration are still required. GCam/Soli files may be present in the image but their ColorOS functionality is not verified. Native 3D Face ID remains dependent on ColorOS biometric framework compatibility.

Requires Android `repo`, Git LFS, working HeckerOS Android 17 build dependencies and root or passwordless sudo for loop-mounting ext4 images. The code does not disable SELinux or automatically authorize ADB clients. GitHub actions validate syntax, isolated source audits, first-stage patch generation and synthetic safety cases; the complete multi-GB Android build can only be verified on a suitable build server.

**If a safety gate fails, no engineering ZIP is produced.** Preserve the full log for further fixes. All output remains in `work/` and is excluded from Git.

## Minimal first-boot profile on unprivileged servers

Use this profile for ColorOS first-boot compatibility before adding Pixel-exclusive apps. It reuses
the already compiled HeckerOS hardware outputs and does not use sudo or rebuild the Android tree.

```bash
python3 -m unittest discover -s tests -p 'test_minimal_boot.py' -v
python3 tools/build_firstboot_images.py --rom-root "$HOME/coloros17-coral/aosp" --rootless --minimal-boot --check-inputs-only
OUT="$PWD/work/engineering-minimal-$(date +%Y%m%d-%H%M%S)"
python3 tools/build_firstboot_images.py --rom-root "$HOME/coloros17-coral/aosp" --rootless --minimal-boot --output "$OUT"
```

This mode skips all optional Pixel app transplants, including Google Camera, IMS userland,
Face ID and Motion Sense app integration. Missing FloralMotionSenseSettings no longer blocks
this profile. ColorOS donor property-context scanning, AVB checks, and super-image assembly
are still required and can stop the build.

The original Pixel boot/kernel/vendor firmware and HALs remain untouched. Therefore this
does not guarantee all biometric/Soli HAL processes are gone and does not establish
VINTF/SELinux/first-boot compatibility. It is still an untested engineering archive,
not a recovery OTA or a verified flashable image.

## Chained AVB rollback location and safe resume

AVB chained images record the rollback slot in the **parent** vbmeta's chain
descriptor, not the chained child's header. For this coral base, parent
`vbmeta.img` declares `vbmeta_system` at slot 1; the child
`vbmeta_system.img` header has location 0. Do not disable AVB or change the
parent descriptor just to satisfy a mistaken child-header check.

Run the `tests/test_chained_avb.py` regression test and use
`--rootless --minimal-boot --check-inputs-only` to verify the baseline
**before** any new multigigabyte image copies.

If the previous failure occurred before image signing and the minimal staging
directory still contains an exact unmodified donor `system.img`, a valid
`vendor-raw.img`, and a completed property-context audit with zero edits,
`--resume-staged --rootless --minimal-boot --output DIR` reuses that same
staging directory. It refuses any edited, signed, or ambiguous staging image.
Otherwise choose a fresh output folder.

```bash
python3 -m unittest discover -s tests -p 'test_chained_avb.py' -v
python3 tools/build_firstboot_images.py --rom-root "$HOME/coloros17-coral/aosp" --rootless --minimal-boot --check-inputs-only
python3 tools/build_firstboot_images.py --rom-root "$HOME/coloros17-coral/aosp" --rootless --minimal-boot --resume-staged --output "$PWD/work/engineering-minimal-20261121-045148"
```

Even a fully signed archive remains an unverified engineering output, not a
recovery ZIP or a known bootable ROM. AVB preflight does not verify Android
framework compatibility, SELinux policy, first-stage mounts, or VINTF.

## Resume after missing target-files archive (signed images preserved)

When ColorOS minimal assembly completes `avbtool verify_image` but stops at
`No AOSP target-files archive after coral build`, **do not** run the original
`--resume-staged` path: the system image is already AVB-signed.

Fetch the latest rootless branch and run:

```bash
python3 -m unittest discover -s tests -p 'test_super_resume.py' -v
python3 tools/build_firstboot_images.py \
  --rom-root "$HOME/coloros17-coral/aosp" \
  --rootless --minimal-boot --resume-signed \
  --output "$PWD/work/engineering-minimal-20261121-045148"
```

The assembly now reads generated metadata directly, preferring the original
target-files `META/misc_info.txt` if available, or an AOSP-generated
`super_empty_intermediates/misc_info.txt` / superimage metadata dictionary.
These values are compared with the pinned coral BoardConfig. No geometry is
invented, and `build_super_image.py` still creates the logical partition image.

If these files genuinely do not exist, generate target-files from the compiled
ROM source without intentionally rebuilding the full ROM:

```bash
cd ~/coloros17-coral/aosp
source build/envsetup.sh
lunch hecker_coral-hecker_suite-userdebug
USE_RBE=true m target-files-package
cd ~/coloros17-coral-port
# Retry the same --resume-signed command above.
```

`--resume-signed` refuses finished output, failed signatures, missing audits,
nonmatching donor content, or incorrect rollback metadata. It does not append
another AVB footer or copy the donor again. Packaging is still an experimental
engineering artifact, **not** a verified flashable ROM.
