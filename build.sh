#!/usr/bin/env bash
# Build an experimental ColorOS17 coral image set with signed AVB and A/B super.
# This is a development-only pipeline. It does not flash or emit a bootable OTA.
set -eo pipefail
PORT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
AOSP_ROOT="$(printenv COLOROS17_AOSP_ROOT || true)"
if [[ -z "$AOSP_ROOT" ]]; then AOSP_ROOT="$HOME/coloros17-coral/aosp"; fi
MANIFEST="https://github.com/its-hecker/HeckerOS.git"
LOCAL="https://github.com/its-hecker/HeckerOs-localmanifest.git"
BRANCH="cnb_latest_stable"
echo "== ColorOS 17 / Pixel 4 XL experimental staging =="
echo "Android tree: $AOSP_ROOT"
echo "This produces an UNTESTED engineering image archive, not an OTA installer."
command -v git >/dev/null
command -v git-lfs >/dev/null
command -v repo >/dev/null
command -v python3 >/dev/null
mkdir -p "$AOSP_ROOT"
cd "$AOSP_ROOT"
if [[ ! -d .repo ]]; then
    repo init -u "$MANIFEST" -b "$BRANCH" --git-lfs
fi
if [[ ! -e .repo/local_manifests ]]; then
    git clone -q -b "$BRANCH" "$LOCAL" .repo/local_manifests
elif [[ -d .repo/local_manifests/.git ]]; then
    echo "Existing local manifest found; refusing to overwrite or reset it."
else
    echo "Unexpected local manifest path; aborting." >&2
    exit 2
fi
repo sync -c --fail-fast --no-clone-bundle --no-tags -j4
echo "Pinning experimental coral first-stage mount layout in isolated tree."
python3 "$PORT_ROOT/tools/bootstrap.py" --audit
python3 "$PORT_ROOT/tools/prepare_device.py" --rom-root "$AOSP_ROOT"
echo "Building coral Android 17 kernel/vendor with AVB verification enabled."
env -u HECKER_BUILD_JOBS USE_RBE=true WITH_AVB=true HECKER_DEVICE=coral \
    HECKER_BUILD_VARIANT=userdebug bash .repo/local_manifests/build.sh
echo "Checking actual ColorOS system and coral vendor/boot geometry."
python3 "$PORT_ROOT/tools/stage_build.py" --rom-root "$AOSP_ROOT"
echo "Assembling an EXPERIMENTAL signed ColorOS17 coral A/B super image."
python3 "$PORT_ROOT/tools/build_firstboot_images.py" --rom-root "$AOSP_ROOT"
echo "Engineering image package: $PORT_ROOT/work/engineering/"
echo "NOT TESTED ON DEVICE. This is NOT a recovery-installable OTA."
