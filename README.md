# ColorOS 17 for Pixel 4 XL (coral)

**Maintainer:** Hecker · **Target:** Pixel 4 XL (`coral`) · **Status:** Stage 0, source/donor compatibility preparation.

A **real ColorOS 17 binary port**, not an AOSP visual theme. The target design combines a third-party PLK110 ColorOS 17 donor GSI with the Pixel's known Android 17 floral kernel, device tree and vendor, then adapts Google Camera, Citadel-backed 3D Face Unlock and Soli Motion Sense.

This is **not bootable or flashable yet**. We have not extracted the donor system, patched framework, assembled an image, or confirmed boot. GitHub contains only scripts, source references and port-specific tests; proprietary images remain on the builder's computer.

## Development

Branch: `dev/coloros17-firstboot` (default `main` remains the landing page).

The exact upstream commits and the donor URL are pinned in [sources.lock.json](sources.lock.json). We use the existing HeckerOS hardware tree, vendor and kernel as read-only base checkouts. Three new ColorOS repositories hold adapters rather than blindly copying hundreds of megabytes of proprietary blobs.

### Run the stage-0 preflight on Linux

```bash
git clone -b dev/coloros17-firstboot https://github.com/its-hecker/ColorOS17-Coral-LocalManifest.git
cd ColorOS17-Coral-LocalManifest
python3 tools/bootstrap.py --audit
python3 tools/donor.py --download --inspect
python3 -m unittest discover -s tests -v
```

The donor downloader saves the official community-uploaded PLK110 GSI locally under `work/donor/`. It downloads **several gigabytes** and does **not** publish the result to GitHub. The downloaded archive's SHA-256 is recorded locally; until corroborated with a trusted hash, it is an input candidate, not a verified release. `--inspect` reads ZIP metadata and image headers, but it **does not build or flash anything**.

The bootstrap clones pinned revisions under `work/`, rechecks revision identity and can run three source audits. Existing checkouts with a different revision are rejected instead of silently reset.

## Repositories

- [ColorOS17-Coral-DeviceTree](https://github.com/its-hecker/ColorOS17-Coral-DeviceTree): Pixel hardware adaptation and checks.
- [ColorOS17-Coral-Vendor](https://github.com/its-hecker/ColorOS17-Coral-Vendor): proprietary HAL availability and compatibility checks; no blobs mirrored.
- [ColorOS17-Floral-Kernel](https://github.com/its-hecker/ColorOS17-Floral-Kernel): pinned floral kernel integration checks.
- [Community OnePlus 7 Pro ColorOS 17 port](https://github.com/nathanatgit/oneplus7-coloros17-port): reference architecture only; its images are incompatible with coral.

See [docs/PORTING_PLAN.md](docs/PORTING_PLAN.md) for milestone boundaries and failure criteria.
