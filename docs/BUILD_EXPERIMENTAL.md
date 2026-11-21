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

## Read-only first-boot VINTF and SELinux input inventory

Once the assembled package's super metadata and actual unpacked boot fstab
have been checked, extract only VINTF XML and record SELinux policy input
presence from the signed ColorOS system and compiled Pixel vendor raw ext4.

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_boot_compat_inventory.py' -v
OUT="$PWD/work/engineering-minimal-20261121-045148"
REPORT="$PWD/work/boot-compat-audit-$(date +%Y%m%d-%H%M%S)"
python3 tools/audit_coloros_boot_compat.py --output "$OUT" --report-dir "$REPORT"
python3 -m json.tool "$REPORT/boot-compat-inventory.json"
```

This audit reads the ext4 images through debugfs, checks XML well-formedness,
lists framework/vendor HAL names and identifies which SELinux input files
exist. It does not run the complete Android checkvintf machinery, does not
reconcile binder ABI, linker namespaces, VNDK or policy rules, and cannot
declare a successful boot. No raw partition data or image is changed.

## Host checkvintf: unresolved /apex/apex-info-list.xml

The `audit_coloros_boot_compat.py` inventory extracts VINTF XML but not the
original ColorOS/Pixel APEX payloads. Running AOSP `checkvintf --check-compat`
without `--dirmap /apex:...` may fail with
`Cannot resolve path /apex/apex-info-list.xml` and cascaded manifest errors.
This indicates incomplete host input setup, not a proven vendor mismatch.

For a *partial base-manifest check*, the helper uses an empty mapped /apex
directory and labels every result `APEX_UNCHECKED`. It does NOT claim full
compatibility, and a `COMPATIBLE` result cannot authorize flashing.

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_check_coloros_vintf_base.py' -v
REPORT=$(find "$PWD/work" -maxdepth 1 -type d -name 'boot-compat-audit-*' | sort | tail -n 1)
python3 tools/check_coloros_vintf_base.py \
  --aosp "$HOME/coloros17-coral/aosp" \
  --audit "$REPORT" \
  --log "$PWD/work/checkvintf-base-coloros-coral.log"
```

The full VINTF check still needs actual donor and Pixel APEX containers,
`apexd_host` activated files and apex-info-list.xml; kernel/runtime metadata
and independent SELinux policy validation are also outstanding. AOSP's
`build/make/tools/releasetools/check_target_files_vintf.py` prepares the
`/apex` mapping and uses `apexd_host` for exactly this reason.

## Vendor-specific HALs missing from the ColorOS framework matrix

`check_coloros_vintf_base.py` may report `INCOMPATIBLE` when the Pixel vendor
declares hardware-specific services that the ColorOS GSI framework matrix does
not mention. Examples include Pixel display, Google Airbrush/SAR/wireless
charging, and LineageOS health/LiveDisplay/touch HALs. Do NOT remove HALs or
disable AVB/SELinux merely to make the compatibility tool pass.

Run the isolated matrix-candidate generator, which parses the actual
`checkvintf` error and requires exact package/interface/instance/version
matches in the exported Pixel vendor manifest before adding any declaration:

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_prepare_coloros_device_fcm.py' -v
REPORT=$(find "$PWD/work" -maxdepth 1 -type d -name 'boot-compat-audit-*' | sort | tail -n 1)
CANDIDATE="$PWD/work/vintf-device-fcm-$(date +%Y%m%d-%H%M%S)"
python3 tools/prepare_coloros_device_fcm.py \
  --aosp "$HOME/coloros17-coral/aosp" \
  --audit "$REPORT" \
  --log "$PWD/work/checkvintf-base-coloros-coral.log" \
  --candidate "$CANDIDATE"
python3 -m json.tool "$CANDIDATE/candidate-report.json"
```

The output path under `vintf/coloros_system/system/etc/vintf/` is an
**uninstalled XML candidate** at `compatibility_matrix.device.xml`. The
generator runs `checkvintf` against this *copy*, not against the signed
`system.img`. A `CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED` result
only means the listed HAL declarations are sufficient for this partial
host check. It is not evidence that the services exist or work at runtime,
nor does it verify APEX, VNDK, linker namespaces or enforcing SELinux.

Do not modify/re-sign the completed engineering images until the candidate
is reviewed against the actual assembled donor and vendor artifacts.

## Build a separate signed engineering image with the compatible Pixel FCM

After `prepare_coloros_device_fcm.py` reports
`CANDIDATE_BASE_VINTF_COMPATIBLE_APEX_UNCHECKED`, integrate that vetted
framework matrix into a NEW minimal boot engineering image. The original
working archive and signed image directory are never edited or overwritten.

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_build_vintf_candidate_images.py' -v
CANDIDATE=$(find "$PWD/work" -maxdepth 1 -type d -name 'vintf-device-fcm-*' | sort | tail -n 1)
BASELINE="$PWD/work/engineering-minimal-20261121-045148"
OUT="$PWD/work/engineering-minimal-vintf-$(date +%Y%m%d-%H%M%S)"
python3 tools/build_vintf_candidate_images.py \
  --rom-root "$HOME/coloros17-coral/aosp" \
  --candidate "$CANDIDATE" \
  --baseline "$BASELINE" \
  --output "$OUT"
ls -lh "$OUT"
```

The builder verifies the candidate against the exact exported Pixel vendor
HALs, reruns the partial host VINTF check, rejects changed baseline boot/AVB
images or a different vendor manifest, then starts from the immutable unsigned
ColorOS donor. It installs only
`/system/etc/vintf/compatibility_matrix.device.xml`, retaining the SELinux
xattr, owner/mode of a neighboring ColorOS platform matrix. It checks ext4
integrity, reaudits property contexts, regenerates `vbmeta_system.img`
with AVB verification enabled, regenerates super and packages a *new* ZIP.

**Caution:** The vendor image and boot image remain those from the original
minimal baseline. This is NOT a runtime-validated port and does not claim
APEX, linker, VNDK, kernel FCM or SELinux policy compatibility. The resulting
engineering ZIP is NOT an OTA or a safe-to-flash ROM release. Do not use a
`COMPATIBLE` base-VINTF result as permission to flash.

### Rebuild validation: existing ColorOS device FCM

The donor may already include a `compatibility_matrix.device.xml` containing
mandatory HALs or legacy shorthand format declarations. These **preexisting**
entries are not new Pixel additions and must remain unchanged. The image
builder now regenerates the expected complete matrix directly from the
original donor ext4 and the reviewed HAL report, compares canonical XML
against the successful candidate, and then replaces the donor matrix while
preserving its original SELinux xattrs, uid/gid and mode. If no such donor
matrix exists, the builder instead creates it using a neighboring VINTF
file's metadata. An unexpected delta stops *before* copying large images.

## Inspect APEX and SELinux inputs after VINTF-integrated build

Run the read-only image inventory before any attempted device testing:

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_audit_apex_selinux_inputs.py' -v
OUT="$PWD/work/engineering-minimal-vintf-20261121-054439"
python3 tools/audit_apex_selinux_inputs.py \
  --output "$OUT" --report "$OUT/apex-selinux-inventory.json"
python3 -m json.tool "$OUT/apex-selinux-inventory.json"
```

The tool lists .apex/.capex containers and the presence of SELinux platform,
system_ext, product and vendor policy inputs. It compares the platform-side
`*sepolicy_and_mapping.sha256` values with the vendor's corresponding
`precompiled_sepolicy.*.sha256` values. A hash mismatch does not alone mean
boot failure: Android may fall back to compiling policy modules, but that
fallback must itself be verified. Do not replace or remove a precompiled
policy merely because the hashes differ. Full APEX activation with
`apexd_host` and CIL validation with `secilc` remain separate future checks.

## Pixel vendor precompiled SELinux policy hash mismatch

The ColorOS `plat`, `system_ext`, and `product` SELinux hash values may all
differ from the Pixel vendor's `precompiled_sepolicy.*.sha256` hash files.
Android init does *not* use that precompiled policy in this situation:
its `OpenSplitPolicy()` path invokes `/system/bin/secilc` with the split
platform, vendor and versioned-mapping CIL files to compile a new policy.
**Never modify hash files to force acceptance of an incompatible precompiled
binary, and never disable enforcing SELinux as a substitute for compilation.**

Run an isolated host-side CIL compilation probe against the actual assembled
ColorOS system.img and Pixel vendor-raw.img, with no image modifications:

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_check_coloros_split_sepolicy.py' -v
OUT="$PWD/work/engineering-minimal-vintf-20261121-054439"
REPORT="$PWD/work/selinux-compile-$(date +%Y%m%d-%H%M%S)"
python3 tools/check_coloros_split_sepolicy.py \
  --output "$OUT" \
  --aosp "$HOME/coloros17-coral/aosp" \
  --report-dir "$REPORT"
python3 -m json.tool "$REPORT/selinux-compile-report.json"
tail -n 100 "$REPORT/secilc.log"
```

Requires the host binary `$HOME/coloros17-coral/aosp/out/host/linux-x86/bin/secilc`;
if absent, build it in the already-compiled Android tree with
`source build/envsetup.sh && lunch hecker_coral-hecker_suite-userdebug &&
USE_RBE=true m secilc` then rerun against a fresh report directory.

The tool reads the vendor `plat_sepolicy_vers.txt`, requires the corresponding
`system/etc/selinux/mapping/<version>.cil`, and exports only the CIL files
that `OpenSplitPolicy()` would use. It attempts compilation with Android-like
`-m -M true -G -N` flags and writes all outputs under a fresh work folder.
By default, it uses the **host compiler's default binary policy version**;
an exact `SEPOLICY_VERSION` from the compiled init can be supplied explicitly
with `--policy-version N`. In either case, this is only a static compiler
probe, not proof the ColorOS system SELinux policy is loadable on Pixel kernel
or that runtime neverallow/enforcing behavior is valid.

If the host compile fails, inspect the first `unknown type`, `Failed to
resolve`, or missing mapping diagnostics rather than suppressing rules.
APEX activation, full VINTF and real first-boot testing remain outstanding.

### Investigating `Re-declaration of type hal_imsrtp`

The host CIL compile may fail with a type/typeattribute name collision
around `hal_imsrtp`. This is a **policy compilation error**, not merely a
precompiled hash mismatch. AOSP `init/selinux.cpp` compiles the system
platform, compatibility mapping, optional system_ext/product, and vendor
versioned/public and vendor CIL inputs together when hashes differ. The
current split-policy test mirrors these CIL input roles, but its default
`secilc` policy version is not necessarily identical to device init.

Before editing anything, record which exported CIL file declares the
conflicting symbol as a type and which declares it as a typeattribute:

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_diagnose_cil_symbol_conflict.py' -v
REPORT="$PWD/work/selinux-compile-20261121-060305"
python3 tools/diagnose_cil_symbol_conflict.py \
  --report "$REPORT/selinux-compile-report.json" \
  --output "$REPORT/hal-imsrtp-declarations.json"
python3 -m json.tool "$REPORT/hal-imsrtp-declarations.json"
```

This diagnostic is read-only, preserves file paths/line numbers and reports
if the exported inputs are insufficient to identify the conflict. Do not
delete or rename HAL symbols, omit a security policy input, change platform
hashes, or disable enforcing as a shortcut. Examine the corresponding
original `.te` declarations, especially Pixel/Qualcomm vendor HAL domains,
against actual donor platform policy before preparing a reviewed patch.

### Confirmed split-CIL collision: ColorOS system_ext vs Pixel vendor

The diagnostic identified **two distinct declarations** in the actual
assembled-image CIL inputs:

- ColorOS `/system_ext/etc/selinux/system_ext_sepolicy.cil:838`:
  `(typeattribute hal_imsrtp)`.
- Pixel `/etc/selinux/vendor_sepolicy.cil:1527`:
  `(type hal_imsrtp)` (from the Pixel Qualcomm imsrtp service domain).

The first host compiler error is therefore not an absent file or a bad
SHA-256 policy hash: it is a real type/typeattribute namespace collision.

To determine whether a narrowly scoped **vendor domain** rename would
allow split policy compilation, run a dry-run against a temporary copy
of the exported vendor CIL. It does NOT modify any actual ext4 image:

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_probe_imsrtp_cil_rename.py' -v
R="$PWD/work/selinux-compile-20261121-060305"
PROBE="$PWD/work/imsrtp-policy-probe-$(date +%Y%m%d-%H%M%S)"
python3 tools/probe_imsrtp_cil_rename.py \
  --report "$R/selinux-compile-report.json" \
  --aosp "$HOME/coloros17-coral/aosp" \
  --output "$PROBE"
cat "$PROBE/probe-report.json"
tail -n 80 "$PROBE/secilc-probe.log"
```

The probe renames the exact CIL domain token `hal_imsrtp` to
`pixel_imsrtp_domain` only inside a *copied* vendor module. It leaves
other tokens such as `hal_imsrtp_exec`, `hal_imsrtp_client` and the
ColorOS `hal_imsrtp` typeattribute untouched. A passing host compile
would justify a follow-up patch to the **isolated ColorOS** Pixel source
checkout with equivalent file contexts and policy references, followed
by regenerating vendor and revalidating all inputs. It would not prove
runtime service correctness or authorize device flashing.

### `Problems processing genfscon rules` after the IMS RTP rename probe

If the temporary IMS RTP domain rename gets past the type/typeattribute error
but secilc then reports `Problems processing genfscon rules`, do not conclude
the policy compiles. `genfscon` labels such as procfs/sysfs paths need another
provenance audit. Android SELinux policy compatibility documentation cautions
against incompatible platform/vendor filesystem labeling rules.

Run the read-only duplicate audit on the exact exported CIL inputs (the
rename probe only changed the `hal_imsrtp` domain token; it did not alter
`genfscon` labels):

```bash
cd ~/coloros17-coral-port
python3 -m unittest discover -s tests -p 'test_diagnose_genfscon_collisions.py' -v
R="$PWD/work/selinux-compile-20261121-060305"
python3 tools/diagnose_genfscon_collisions.py \
  --report "$R/selinux-compile-report.json" \
  --output "$R/genfscon-collisions.json"
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('work/selinux-compile-20261121-060305/genfscon-collisions.json').read_text())
print('conflicting fs/path rules:',r['different_context_path_count'])
for row in r['different_context_examples'][:15]:
 print(row['filesystem'],row['path'])
 for item in row['declarations']:
  print(' ',item['role'],item['source'],item['line'],item['declaration'][:160])
PY
```

This reports duplicate `(filesystem, path)` pairs from the actual extracted
policy modules, distinguishing identical from differing declarations and
showing original CIL file and line numbers. If no duplicates appear, or
the duplicates are identical, the root cause may be another genfscon
validation issue requiring a more verbose compiler/source-level diagnosis.
The tool never changes an image, rule, hash, or device.
