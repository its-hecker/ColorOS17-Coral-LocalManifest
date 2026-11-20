# Optional raw ext4 image sizing — offline stage only

Our verified PLK110 GSI supplies a large **6,584,750,080-byte raw ext4 `system.img`**. This consumes most of coral's approximately 8.05 GB A/B dynamic-partition group. We must measure Pixel vendor/product/system_ext and the donor's actual populated ext4 blocks before determining whether it fits.

The helper `tools/shrink_system_ext4.py` is optional and does **not** alter the donor image. It checks ext4 read-only, makes a separate staging copy, runs `resize2fs -M` on the staging image, checks ext4 again and writes resulting SHA-256. It preserves inode metadata and labels because resizing takes place at filesystem level rather than re-extracting files.

```bash
python3 tools/shrink_system_ext4.py \
  --input work/donor/system-for-inspection.img \
  --output work/port/system-compact.img \
  --execute
```

**Important:** Do not run on an unverified or corrupted filesystem. The resulting image remains **not flashable**: matching AVB descriptors, image contents, partition allocation, boot integration and testing are still missing. There is no image here yet.
