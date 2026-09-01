import unittest

from logic_core import generate_commands


class GenerateCommandsTests(unittest.TestCase):
    def generate(self, text):
        return generate_commands(text, skip_errors=False, mode="CONFIG")

    def test_route_aliases_generate_the_same_command(self):
        expected = self.generate("2838123456 route HCM")
        self.assertEqual(expected, self.generate("2838123456 to HCM"))
        self.assertEqual(expected, self.generate("2838123456 HCM"))

    def test_invalid_site_is_rejected_instead_of_defaulted(self):
        for number in ("918433694", "1382223334", "19001234"):
            with self.subTest(number=number):
                result = self.generate(f"{number} route BAD")
                self.assertEqual(1, len(result))
                self.assertIn("không hợp lệ", result[0])
                self.assertTrue(result[0].startswith("# [LỖI"))

    def test_138_only_accepts_hcm_or_hni(self):
        self.assertIn("RC=742", self.generate("1382223334 route HCM")[0])
        self.assertIn("RC=703", self.generate("1382223334 route HNI")[0])
        self.assertTrue(self.generate("1382223334 route IMS")[0].startswith("# [LỖI"))


if __name__ == "__main__":
    unittest.main()
