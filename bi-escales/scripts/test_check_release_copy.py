"""Release-copy scanner tests without plaintext disallowed terminology."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "release_copy", Path(__file__).with_name("check_release_copy.py")
)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


class CopyPreflightTest(unittest.TestCase):
    def test_spellings_and_separators(self):
        stem = bytes.fromhex("717565626563").decode()
        self.assertTrue(module.prohibited(stem))
        self.assertTrue(module.prohibited(stem.upper()))
        self.assertTrue(module.prohibited(stem[:2] + "\u00e9" + stem[3:]))
        self.assertTrue(module.prohibited("-".join(stem)))
        self.assertTrue(module.prohibited(stem + "ois"))
        self.assertFalse(module.prohibited("French non-profit serving marine projects"))

    def test_scans_release_drafts(self):
        with tempfile.TemporaryDirectory() as scratch:
            draft = Path(scratch) / "submission.md"
            draft.write_text("Funding a marine conservation project")
            self.assertEqual(module.scan([Path(scratch)]), ([], []))
            draft.write_text(bytes.fromhex("717565626563").decode())
            blocked, errors = module.scan([Path(scratch)])
            self.assertEqual(blocked, [str(draft)])
            self.assertFalse(errors)

    def test_missing_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as scratch:
            blocked, errors = module.scan([Path(scratch) / "absent.txt"])
            self.assertFalse(blocked)
            self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
