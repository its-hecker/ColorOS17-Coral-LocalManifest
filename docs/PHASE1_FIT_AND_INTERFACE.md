# Coral ColorOS 17 — phase 1 engineering findings

## Verified donor and partition size

The pinned PLK110 Axis GSI has **one raw ext4 system image** (6,584,750,080 bytes) containing `/system`, `/product`, `/system_ext`, several `/my_*` directories and an `/odm` directory. [Deep inspection](https://github.com/its-hecker/ColorOS17-Coral-LocalManifest/actions/runs/44828896866).

The pinned coral device tree declares an **8,048,869,376-byte logical group per slot**. With 32 MiB reserved, **1,430,564,864 bytes** remain for the actual vendor image and any other separate dynamic partitions. This assumes `product` and `system_ext` are *embedded in the ColorOS system image* and not independently flashed. The AVB chain and dynamic partition metadata must agree with that configuration.

## Vendor source inventory — measured, not an image-size guarantee

[Source audit run 44830676829](https://github.com/its-hecker/ColorOS17-Coral-LocalManifest/actions/runs/44830676829):

| Pinned vendor source category | Logical source bytes | Files |
| --- | ---: | ---: |
| `proprietary/vendor` | 749,750,890 | 1,579 |
| `proprietary/product` | 181,063,896 | 217 |
| `proprietary/system_ext` | 35,229,833 | 49 |

The first row is *not* the final vendor partition size. It omits AOSP and generated vendor modules, metadata, filesystem slack and alignment; it could also count source blobs not included in the final ROM. It is strictly a source payload inventory. Separate Pixel product/system_ext source assets would need individual compatibility review **before selectively integrating them into the donor's embedded directories**.

## Required compatibility sequence

1. **Framework compatibility:** read ColorOS's actual framework VINTF matrix and `/system/product` and `/system/system_ext` link targets. Compare against the pinned coral manifest and later the *full assembled vendor/odm manifest fragments*. Report unmatched HAL *names* as tentative findings only; versions/interfaces must be verified with `checkvintf`.
2. **Preserve Pixel runtime:** audit camera, IMS, RIL and eSIM files from the Pixel vendor product/system_ext source. Never overwrite same-name ColorOS APKs without verifying package signatures, permissions and library dependencies.
3. **Filesystem fit:** build or obtain a complete `vendor.img` from the unchanged coral Android 17 base, measure expanded image geometry and run `tools/partition_budget.py --embed-product --embed-system-ext --vendor-img ...`. Run actual super metadata assembly checks before concluding that it fits.
4. **Mount/boot:** maintain coral's vendor, metadata and encrypted userdata fstab lines; adapt only the separately mounted product/system_ext rows after verifying donor embedded filesystem behavior. Review AVB/vbmeta descriptors rather than disabling them to suppress errors.
5. **SELinux:** compare actual vendor/odm property contexts with ColorOS system-side contexts and generate narrowly scoped collision candidates. Keep enforcing policy as the goal.
6. **System image:** only after the above gates can an isolated image-repack pipeline be implemented, with source hashes and explicit output manifests. No bootable ROM has been produced.

### Non-negotiable boundaries

No OnePlus boot/vendor/modem images, no factory ADB authorized host keys, no fake biometric authentication, no arbitrary permissive SELinux workarounds, and no flashing until the image has passed the device-specific safety checks. No proprietary firmware is committed here.

## Existing tools

- `tools/vendor_source_footprint.py`: measured source-side logical payload.
- `tools/pixel_runtime_dependencies.py`: candidate Pixel components hidden by embedded ColorOS system layout.
- `tools/audit_donor_interfaces.py`: read-only ColorOS framework requirements and mount links.
- `tools/firstboot_preflight.py`: pinned coral fstab candidate and fail-closed partition geometry.
- `tools/partition_budget.py`: separate signed-image sizes when available.

All changes are on `dev/coloros17-firstboot`; no main branch or baseline HeckerOS repository is altered.
