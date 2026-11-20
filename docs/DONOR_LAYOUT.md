# ColorOS 17 PLK110 donor layout — verified observations

From [GitHub Actions run 44826418869](https://github.com/its-hecker/ColorOS17-Coral-LocalManifest/actions/runs/44826418869):

- Archive: `ColorOS-17-PLK110-1789230075256-18092026-AxisGSI.zip`.
- Archive length: **3,369,547,979 bytes**.
- SHA-256: `2842e697e30a04513050eefbf295e1f7911733ef9d7e964a028ec91e75efef64`.
- Exactly **one** ZIP entry: `system.img`.
- Uncompressed `system.img`: **6,584,750,080 bytes**.
- Embedded filesystem: **raw ext4**, not EROFS and not Android sparse.
- ZIP central directory is readable; full ZIP CRC or filesystem consistency was not checked by that initial job.

## Impact on Pixel 4 XL

The coral `BoardConfig-common.mk` defines `system`, `system_ext`, `product`, and `vendor` as A/B dynamic partitions within a **8,048,869,376-byte per-slot group** (super partition 16,106,127,360 bytes). The donor's entire raw `system.img` takes about 6.585 GB, leaving at most **1,464,119,296 bytes** for all other partitions *and metadata*. This is not yet proven to fit. Real Pixel vendor/product/system_ext image sizes must be measured before preparing an install.

The selected donor uses ext4, which matches the existing coral system fstab. **Do not apply the optional EROFS fstab adapter to this donor.**

## Still to examine

The image is a system-only GSI. It may pack `system_ext`, `product` or OPPO `my_*` content as nested directories. The ZIP listing alone cannot prove its internal directory structure. The `inspect_ext4_contents.py` inspector reads ext4 directory and superblock metadata (no privileged mounts, no image publishing) and reports its layout. Additional source-side compatibility transformations must be selected after these findings.
