import unittest

from thyclass.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_doctor_exits_zero(self):
        self.assertEqual(main(["doctor"]), 0)

    def test_net_dry_run(self):
        self.assertEqual(main(["net", "--off", "--dry-run"]), 0)
        self.assertEqual(main(["net", "--on", "--dry-run"]), 0)
        self.assertEqual(main(["net", "--status"]), 0)

    def test_net_conflicting_flags(self):
        self.assertEqual(main(["net", "--off", "--on"]), 2)

    def test_no_role_prints_help(self):
        self.assertEqual(main([]), 0)

    def test_parser_has_expected_subcommands(self):
        parser = build_parser()
        actions = [a.dest for a in parser._actions if a.dest == "role"]
        self.assertTrue(actions)


if __name__ == "__main__":
    unittest.main()
