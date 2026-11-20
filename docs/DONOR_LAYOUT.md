# Verified PLK110 ColorOS 17 / Pixel 4 XL layout

## Firmware identity

The PLK110 AxisGSI archive was downloaded and SHA-256 checked in GitHub Actions [run 44826418869](https://github.com/its-hecker/ColorOS17-Coral-LocalManifest/actions/runs/44826418869):

- Filename: `ColorOS-17-PLK110-1789230075256-18092026-AxisGSI.zip`
- ZIP bytes: **3,369,547,979**
- ZIP SHA-256: `2842e697e30a04513050eefbf295e1f7911733ef9d7e964a028ec91e75efef64`
- ZIP entries: exactly **one**, `system.img`
- Raw `system.img`: **6,584,750,080 bytes**, **ext4** (not EROFS/sparse)

In the separate read-only [ext4 interior inspection run 44828896866](https://github.com/its-hecker/ColorOS17-Coral-LocalManifest/actions/runs/44828896866), `debugfs` showed:

- Populated `/system`, `/system_ext`, and `/product` directories at **ext4 filesystem root**.
- Populated `/my_product`, `/my_stock`, `/my_bigball`, `/my_carrier`, `/my_company`, `/my_engineering`, `/my_heytap`, `/my_manifest`, `/my_preload`, `/my_region`, `/my_reserve`, plus `/odm`.
- Entries `/system/product` and `/system/system_ext` exist, but their exact link types/targets have not yet been independently verified.

Ext4 superblock: **1,607,605 blocks**, **39,791 free blocks**, **4,096-byte blocks**, filesystem state **clean**. `resize2fs -P` reported **1,607,605 minimum blocks**, equal to current size; don't assume compaction is possible.

## Coral mount compatibility

The pinned floral device tree's original first-stage fstab mounts **four** A/B logical partitions: `system`, `vendor`, `product`, `system_ext`, all as ext4. Flashing the single GSI system.img while keeping **separate Pixel product/system_ext mounts** would hide ColorOS's embedded `/product` and `/system_ext` content.

Generate a **candidate**, not a flashed patch:

```bash
python3 tools/bootstrap.py --audit
python3 tools/firstboot_preflight.py
```

The candidate comments out the two conflicting mount rows while keeping `system`, `vendor`, encryption, and remaining fstab flags unchanged. See adapter [patch_fstab.py](https://github.com/its-hecker/ColorOS17-Coral-DeviceTree/blob/dev/coloros17-firstboot/tools/patch_fstab.py).

## Capacity warning

Coral group capacity: **8,048,869,376 bytes**. Donor system raw image: **6,584,750,080 bytes**. Remainder: **1,464,119,296 bytes** for Pixel vendor and metadata (before reserve). Since `product` and `system_ext` are embedded, separate images should not be included in a *candidate* size plan. Their absence in an eventual boot package still needs AVB/partition-table validation.

No assembled vendor image has been measured; budget is **unverified**. The donor's nearly full ext4 cannot be assumed shrinkable.

## First-boot blockers

1. Measure actual assembled coral `vendor.img` and calculate dynamic partition fit.
2. Verify GSI root symlink targets and ColorOS first-stage init environment.
3. Reconcile Pixel vendor property contexts, VINTF/SELinux and ColorOS system policy.
4. Rebuild/check correct AVB/vbmeta descriptors; **do not** deploy unverified test keys or globally disable verification as a shortcut.
5. Inspect/remove any donor-supplied ADB authorization data that is not from the device owner.
6. Produce an isolated, reversible test image and capture initial boot logs. **No bootable image exists yet.**
