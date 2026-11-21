"""Synthetic ext4 tests for rootless image editing; no root or loop mounts."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rootless_ext4 import Ext4, check_image, copy_node


@unittest.skipUnless(shutil.which("debugfs") and shutil.which("mke2fs") and
                     shutil.which("e2fsck"), "requires e2fsprogs utilities")
class RootlessExt4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.source = directory / "source.img"
        self.target = directory / "target.img"
        for image in (self.source, self.target):
            with image.open("wb") as f:
                f.truncate(32 * 1024 * 1024)
            subprocess.run(["mke2fs", "-q", "-t", "ext4", "-F", str(image)],
                           check=True, capture_output=True)
        self.src = Ext4(self.source)
        self.dst = Ext4(self.target)

    def label(self, filesystem, name):
        filesystem.set_xattr(name, "security.selinux",
                             b"u:object_r:system_file:s0\x00")

    def test_regular_file_metadata_and_content(self):
        infile = Path(self.temp.name) / "hello.txt"
        infile.write_bytes(b"test contents\n")
        self.src.create("/source.txt", "regular", infile)
        self.label(self.src, "/source.txt")
        self.src.cmd("sif /source.txt uid 1000", write=True)
        self.src.cmd("sif /source.txt gid 1001", write=True)
        self.src.cmd("sif /source.txt mode 33184", write=True)
        copy_node(self.src, self.dst, "/source.txt", "/copied.txt")
        self.assertEqual(self.dst.info("/copied.txt")["uid"], 1000)
        self.assertEqual(self.dst.info("/copied.txt")["gid"], 1001)
        self.assertEqual(self.dst.info("/copied.txt")["mode"], 0o640)
        self.assertEqual(self.dst.xattr("/copied.txt", "security.selinux"),
                         b"u:object_r:system_file:s0\x00")
        check_image(self.target)

    def test_directory_tree(self):
        infile = Path(self.temp.name) / "nested.txt"
        infile.write_bytes(b"nested data")
        self.src.create("/folder", "directory")
        self.label(self.src, "/folder")
        self.src.create("/folder/nested", "regular", infile)
        self.label(self.src, "/folder/nested")
        copy_node(self.src, self.dst, "/folder", "/newfolder")
        self.assertEqual(self.dst.info("/newfolder/nested")["size"], 11)
        check_image(self.target)

    def test_missing_label_rejected(self):
        infile = Path(self.temp.name) / "bad.txt"
        infile.write_bytes(b"bad")
        self.src.create("/bad.txt", "regular", infile)
        with self.assertRaisesRegex(ValueError, "Missing source SELinux label"):
            copy_node(self.src, self.dst, "/bad.txt", "/bad.txt")


if __name__ == "__main__":
    unittest.main()
