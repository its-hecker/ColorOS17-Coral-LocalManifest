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
