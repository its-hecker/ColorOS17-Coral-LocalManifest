#!/usr/bin/env python3
"""Rootless ext4 edits for an EXPERIMENTAL, untested ColorOS/coral image.

Uses e2fsprogs' debugfs on *regular image files*, never devices.  Source
ownership, file types, permissions and every extended attribute are checked
after copying.  Any unsupported metadata stops assembly rather than silently
dropping a security label.  Does not certify SELinux/VINTF/AVB runtime behavior.
"""
import json
import os
import re
import shutil
import stat as statmod
import subprocess
import sys
import tempfile
from pathlib import Path

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.+@-]+$")
LS_ROW = re.compile(r"^/(\d+)/([0-7]+)/(\d+)/(\d+)/([^/]+)/([^/]*)/$")
ATTR = re.compile(r"^\s*([a-zA-Z0-9_.-]+)\s+\(\d+\)\s*=", re.M)


def safe(path):
    p = Path(str(path))
    if not str(p).startswith("/") or not p.parts[1:]:
        raise ValueError("Refusing nonabsolute image path: " + str(path))
    if any(not SAFE_NAME.fullmatch(x) for x in p.parts[1:]):
        raise ValueError("Unsupported image path component: " + str(path))
    return str(p)


class Ext4:
    def __init__(self, image):
        self.image = Path(image).resolve()
        if not self.image.is_file():
            raise ValueError("Missing ext4 image " + str(image))
        if not shutil.which("debugfs"):
            raise ValueError("debugfs not installed")

    def cmd(self, instruction, write=False):
        argv = ["debugfs"]
        if write:
            argv.append("-w")
        argv += ["-R", instruction, str(self.image)]
        env = dict(os.environ, DEBUGFS_PAGER="cat", PAGER="cat")
        p = subprocess.run(argv, text=True, capture_output=True, env=env)
        errors = [s for s in p.stderr.splitlines()
                  if s.strip() and not re.match(r"^debugfs \d", s.strip())]
        # debugfs commonly returns exit code 0 even when a subcommand failed.
        if p.returncode or errors:
            raise RuntimeError("debugfs failed: " + instruction + ": " +
                               "; ".join(errors or [p.stdout[-300:]]))
        return p.stdout

    def info(self, path):
        path = safe(path)
        raw = self.cmd("stat " + path)
        ty = re.search(r"\bType:\s*(regular|directory|symlink)\b", raw)
        mode = re.search(r"\bMode:\s*([0-7]+)\b", raw)
        user = re.search(r"\bUser:\s*(\d+)\s+Group:\s*(\d+)", raw)
        size = re.search(r"\bSize:\s*(\d+)", raw)
        links = re.search(r"\bLinks:\s*(\d+)", raw)
        if not all((ty, mode, user, size, links)):
            raise ValueError("Cannot parse ext4 inode metadata for " + path)
        return {"type": ty.group(1), "mode": int(mode.group(1), 8),
                "uid": int(user.group(1)), "gid": int(user.group(2)),
                "size": int(size.group(1)), "links": int(links.group(1))}

    def exists(self, path):
        path = safe(path)
        p = subprocess.run(["debugfs", "-R", "stat " + path, str(self.image)],
                           capture_output=True, text=True)
        if "File not found" in p.stderr or "not found by ext2_lookup" in p.stderr:
            return False
        self.info(path)  # Fail closed on other errors and unsupported types.
        return True

    def children(self, path):
        result = []
        for row in self.cmd("ls -p " + safe(path)).splitlines():
            row = row.strip()
            if not row:
                continue
            m = LS_ROW.fullmatch(row)
            if not m:
                raise ValueError("Unrecognized debugfs ls -p row: " + row)
            name = m.group(5)
            if name in (".", ".."):
                continue
            if not SAFE_NAME.fullmatch(name):
                raise ValueError("Unsupported filename: " + name)
            result.append(name)
        return result

    def attrs(self, path):
        raw = self.cmd("ea_list " + safe(path))
        names = ATTR.findall(raw)
        if "security.selinux" in raw and "security.selinux" not in names:
            raise ValueError("Could not parse SELinux xattr: " + path)
        return sorted(set(names))

    def xattr(self, path, name):
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("Unsafe xattr name: " + name)
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "attr.bin"
            self.cmd("ea_get -f " + str(dst) + " " + safe(path) + " " + name)
            if not dst.is_file():
                raise ValueError("Missing xattr export for " + str(path))
            return dst.read_bytes()

    def set_xattr(self, path, name, data):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "attr.bin"
            src.write_bytes(data)
            self.cmd("ea_set -f " + str(src) + " " + safe(path) +
                     " " + name, write=True)

    def export_file(self, path, dest):
        self.cmd("dump " + safe(path) + " " + str(dest))
        if not dest.is_file():
            raise RuntimeError("debugfs did not export " + str(path))

    def create(self, path, kind, source=None):
        path = safe(path)
        if self.exists(path):
            raise ValueError("Refusing to overwrite image object " + path)
        if kind == "directory":
            self.cmd("mkdir " + path, write=True)
        elif kind == "regular":
            if source is None:
                raise ValueError("Missing file contents")
            self.cmd("write " + str(source) + " " + path, write=True)
        elif kind == "symlink":
            if source is None or not isinstance(source, str) or not source:
                raise ValueError("Missing symlink destination")
            if any(c.isspace() or c in "'\"" for c in source):
                raise ValueError("Unsupported symlink destination: " + source)
            self.cmd("symlink " + path + " " + source, write=True)
        else:
            raise ValueError("Unsupported ext4 file type: " + kind)

    def restore(self, path, metadata, xattrs):
        mode = metadata["mode"] | {
            "directory": statmod.S_IFDIR, "regular": statmod.S_IFREG,
            "symlink": statmod.S_IFLNK}[metadata["type"]]
        for field, value in (("uid", metadata["uid"]), ("gid", metadata["gid"]),
                             ("mode", mode)):
            self.cmd("sif " + safe(path) + " " + field + " " +
                     str(value), write=True)
        for name, value in xattrs.items():
            self.set_xattr(path, name, value)
        seen = self.info(path)
        for field in ("type", "mode", "uid", "gid"):
            if seen[field] != metadata[field]:
                raise ValueError("Image metadata differs: " + path + " " + field)
        if self.attrs(path) != sorted(xattrs):
            raise ValueError("Xattr list differs at " + path)
        for name, value in xattrs.items():
            if self.xattr(path, name) != value:
                raise ValueError("Xattr differs at " + path + ": " + name)


def copy_node(src, dst, srcpath, dstpath):
    srcpath, dstpath = safe(srcpath), safe(dstpath)
    meta = src.info(srcpath)
    if meta["type"] != "directory" and meta["links"] != 1:
        raise ValueError("Hardlinked inode needs special handling: " + srcpath)
    attrs = {name: src.xattr(srcpath, name) for name in src.attrs(srcpath)}
    if "security.selinux" not in attrs:
        raise ValueError("Missing source SELinux label: " + srcpath)
    if meta["type"] == "directory":
        dst.create(dstpath, "directory")
        for child in src.children(srcpath):
            copy_node(src, dst, srcpath + "/" + child, dstpath + "/" + child)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "contents"
            src.export_file(srcpath, file)
            if meta["type"] == "regular":
                if file.stat().st_size != meta["size"]:
                    raise ValueError("File size mismatch: " + srcpath)
                dst.create(dstpath, "regular", file)
            else:
                # debugfs dump exposes the symlink inode contents.
                target = file.read_bytes().decode("utf-8")
                dst.create(dstpath, "symlink", target)
    dst.restore(dstpath, meta, attrs)
    if meta["type"] == "regular":
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            src.export_file(srcpath, a)
            dst.export_file(dstpath, b)
            if a.read_bytes() != b.read_bytes():
                raise ValueError("Copied file differs: " + dstpath)


def replace_file(dst, path, hostfile):
    """Recreate a regular donor file with identical mode, owner and xattrs."""
    path = safe(path)
    meta = dst.info(path)
    if meta["type"] != "regular" or meta["links"] != 1:
        raise ValueError("Unsafe context-file replacement " + path)
    attrs = {name: dst.xattr(path, name) for name in dst.attrs(path)}
    if "security.selinux" not in attrs:
        raise ValueError("Context file missing SELinux xattr: " + path)
    dst.cmd("rm " + path, write=True)
    dst.create(path, "regular", hostfile)
    dst.restore(path, meta, attrs)
    with tempfile.TemporaryDirectory() as tmp:
        actual = Path(tmp) / "readback"
        dst.export_file(path, actual)
        if actual.read_bytes() != Path(hostfile).read_bytes():
            raise ValueError("Context file content mismatch: " + path)


def file_bytes(image, path):
    info = image.info(path)
    if info["type"] == "directory":
        return sum(file_bytes(image, path + "/" + child)
                   for child in image.children(path))
    return info["size"] if info["type"] == "regular" else 0


def check_image(image):
    p = subprocess.run(["e2fsck", "-fn", str(image)], capture_output=True,
                       text=True)
    if p.returncode:
        raise RuntimeError("ext4 fsck rejected " + str(image) + "\n" +
                           (p.stdout + p.stderr)[-2000:])
