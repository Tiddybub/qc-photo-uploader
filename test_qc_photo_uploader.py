import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import qc_photo_uploader as qc


class QcPhotoUploaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.card = root / "DCIM" / "100MSDCF"
        self.dest = root / "drive"
        self.card.mkdir(parents=True)
        self.dest.mkdir()
        for n in range(1, 9):
            (self.card / f"DSC{n:05d}.JPG").write_bytes(b"\xff\xd8 fake jpg %d" % n)
        (self.card / "notes.txt").write_text("not a photo")
        self.marks = root / "marks.txt"

    def write_marks(self, text):
        self.marks.write_text(text, encoding="utf-8")

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = qc.main([str(self.card), str(self.marks), str(self.dest), *extra])
        return code, out.getvalue() + err.getvalue()

    def files_in(self, customer):
        return sorted(p.name for p in qc.folder_for(self.dest, customer).iterdir())

    def test_boundaries(self):
        self.write_marks("DSC00001.JPG Jane Doe\ndsc00004.jpg John Smith\n")
        code, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(self.files_in("Jane Doe"), ["DSC00001.JPG", "DSC00002.JPG", "DSC00003.JPG"])
        self.assertEqual(self.files_in("John Smith"), [f"DSC{n:05d}.JPG" for n in range(4, 9)])
        self.assertTrue((self.card / "DSC00001.JPG").exists(), "photos must be copied, not moved")

    def test_repeat_name_merges_into_one_folder(self):
        self.write_marks("DSC00001.JPG Jane Doe\nDSC00003.JPG John Smith\nDSC00006.JPG jane  doe\n")
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["Jane Doe QC", "John Smith QC"])
        self.assertEqual(self.files_in("Jane Doe"),
                         ["DSC00001.JPG", "DSC00002.JPG", "DSC00006.JPG", "DSC00007.JPG", "DSC00008.JPG"])
        self.assertIn("Jane Doe QC: 5 photo(s)", output)

    def test_carry_over(self):
        self.write_marks("DSC00003.JPG John Smith\n")
        self.assertEqual(self.run_cli()[0], 2, "photos before the first name page need --carry-over")
        code, _ = self.run_cli("--carry-over", "Jane Doe")
        self.assertEqual(code, 0)
        self.assertEqual(self.files_in("Jane Doe"), ["DSC00001.JPG", "DSC00002.JPG"])

    def test_verification_detects_bad_and_duplicate_copies(self):
        self.write_marks("DSC00001.JPG Jane Doe\nDSC00005.JPG John Smith\n")
        plan = qc.build_plan(qc.list_photos(self.card), qc.read_marks(self.marks))
        qc.copy_photos(plan, self.dest)
        self.assertEqual(qc.verify(plan, self.dest), [])

        (qc.folder_for(self.dest, "Jane Doe") / "DSC00002.JPG").write_bytes(b"corrupt")
        (qc.folder_for(self.dest, "John Smith") / "DSC00003.JPG").write_bytes(b"\xff\xd8 fake jpg 3")
        (qc.folder_for(self.dest, "John Smith") / "DSC00006.JPG").unlink()
        problems = qc.verify(plan, self.dest)
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("DSC00002.JPG: copy"))
        self.assertTrue(problems[1].startswith("DSC00003.JPG: expected only"))
        self.assertIn("no folder", problems[2])

    def test_verification_failure_keeps_card(self):
        self.write_marks("DSC00001.JPG Jane Doe\n")
        trashed = []
        real_copy = qc.copy_photos

        def copy_then_corrupt(plan, dest):
            real_copy(plan, dest)
            (qc.folder_for(dest, "Jane Doe") / "DSC00004.JPG").write_bytes(b"corrupt")

        with mock.patch.object(qc, "load_send2trash", return_value=trashed.append), \
                mock.patch.object(qc, "copy_photos", copy_then_corrupt):
            code, output = self.run_cli("--erase-card")
        self.assertEqual(code, 1)
        self.assertIn("Verification FAILED", output)
        self.assertEqual(trashed, [])

    def test_erase_card_trashes_only_verified_photos(self):
        self.write_marks("DSC00001.JPG Jane Doe\n")
        trashed = []
        with mock.patch.object(qc, "load_send2trash", return_value=trashed.append):
            code, _ = self.run_cli("--erase-card")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(Path(p).name for p in trashed), [f"DSC{n:05d}.JPG" for n in range(1, 9)])

    def test_erase_card_refuses_without_send2trash(self):
        self.write_marks("DSC00001.JPG Jane Doe\n")
        with mock.patch.object(qc, "load_send2trash", return_value=None):
            code, output = self.run_cli("--erase-card")
        self.assertEqual(code, 2)
        self.assertIn("send2trash", output)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_dry_run_changes_nothing(self):
        self.write_marks("DSC00001.JPG Jane Doe\nDSC00004.JPG John Smith\n")
        code, output = self.run_cli("--dry-run", "--erase-card")
        self.assertEqual(code, 0)
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(len(list(self.card.iterdir())), 9)
        self.assertIn("DSC00004.JPG -> ", output)
        self.assertIn("John Smith QC: 5 photo(s)", output)

    def test_existing_different_file_is_not_overwritten(self):
        self.write_marks("DSC00001.JPG Jane Doe\n")
        folder = qc.folder_for(self.dest, "Jane Doe")
        folder.mkdir()
        (folder / "DSC00001.JPG").write_bytes(b"older photo")
        code, output = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("not overwriting", output)
        self.assertEqual((folder / "DSC00001.JPG").read_bytes(), b"older photo")


if __name__ == "__main__":
    unittest.main()
