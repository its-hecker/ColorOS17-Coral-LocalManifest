#!/usr/bin/env bash
# Build coral hardware in a separate Android tree and stage ColorOS17 GSI.
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
echo "Only staged images and reports will be generated. NOT FLASHABLE."
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
echo "Building pinned coral Android 17 hardware baseline."
env -u HECKER_BUILD_JOBS USE_RBE=true HECKER_DEVICE=coral \
    HECKER_BUILD_VARIANT=userdebug bash .repo/local_manifests/build.sh
echo "Checking ColorOS donor and generated coral vendor/boot images."
python3 "$PORT_ROOT/tools/stage_build.py" --rom-root "$AOSP_ROOT"
echo "Reports in $PORT_ROOT/work/stage"
echo "These outputs are NOT a flashable ColorOS ROM."
