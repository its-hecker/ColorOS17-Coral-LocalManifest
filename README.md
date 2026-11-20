# ColorOS 17 for Pixel 4 XL (coral)

**Maintainer:** Hecker · **Target:** Pixel 4 XL (`coral`) · **Status:** Stage 2, one-command experimental image-assembly pipeline (boot unverified).

A **real ColorOS 17 binary port**, not an AOSP visual theme. The target design combines a third-party PLK110 ColorOS 17 donor GSI with the Pixel's known Android 17 floral kernel, device tree and vendor, then adapts Google Camera, Citadel-backed 3D Face Unlock and Soli Motion Sense.

This is **not bootable or flashable yet**. We have inspected the donor ext4 image's embedded partition directories and generated an initial coral fstab compatibility candidate. The experimental build script now stages Pixel camera/telephony/Oslo components, performs guarded property-context repairs, signs AVB metadata and generates a sparse super image. **No successful device boot or final compatibility has been verified.** GitHub contains only scripts, source references and port-specific tests; proprietary images remain on the builder's computer.

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


## Verified ColorOS 17 donor / first-boot candidate

- PLK110 donor SHA-256: `2842e697e30a04513050eefbf295e1f7911733ef9d7e964a028ec91e75efef64`.
- One **6,584,750,080-byte raw ext4 `system.img`**, with embedded `/system_ext`, `/product`, `/my_product`, `/my_stock` and other `my_*` directories.
- Coral's existing fstab mounts separate product/system_ext; first-boot candidate comments out these rows to expose the donor directories. Vendor and encrypted userdata mount rows remain untouched.
- Physical fit, first-boot AVB descriptors, linker/SELinux/VINTF compatibility and donor's embedded ADB key require further validation. The filesystem is near full and its estimated minimum size equals the current image size.

See [verified donor layout](docs/DONOR_LAYOUT.md) and [first-boot candidate tool](tools/firstboot_preflight.py). The current candidate workflow publishes **only a generated fstab and text reports**, never a flashable image.


## One-command experimental staging build (ServerHive / Ubuntu)

From a Linux build server that has the Android repo tool, Git LFS and Android
build prerequisites, run:

```bash
git clone -b dev/coloros17-firstboot \
  https://github.com/its-hecker/ColorOS17-Coral-LocalManifest.git ~/coloros17-coral-port
cd ~/coloros17-coral-port
bash build.sh
```

The entrypoint creates a **separate** Android tree under
`~/coloros17-coral/aosp`, syncs the maintained HeckerOS Android 17
coral baseline, builds the original ROM's hardware images, downloads the pinned
PLK110 ColorOS 17 GSI and stages fstab/BoardConfig candidates. Source/hardware
compatibility and real vendor image size are validated. Unmodified HeckerOS
workspaces are left alone.

**This is not yet a real ColorOS ROM image build.** The pipeline deliberately
does not flash, install, release, sign an unverified vbmeta, merge proprietary
packages blindly or claim the resulting GSI is compatible with coral. It leaves
staging files under `work/stage/` with explicit unresolved blockers.
The correct ColorOS boot/SELinux/VINTF/AVB integration must be established and
tested on a Pixel 4 XL before any ROM package can responsibly be called bootable.


## Experimental image build

See [the single-command build and safety requirements](docs/BUILD_EXPERIMENTAL.md). The command invokes `build.sh`, which checks out and compiles coral hardware in an isolated folder, assembles a ColorOS engineering image archive, and **fails instead of silently bypassing AVB/SELinux problems**. No recovery-flashable OTA or working first boot is claimed.
