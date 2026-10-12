import unittest
from hello_match import matches_hello


class MatchTests(unittest.TestCase):
    def test_hello(self):
        for text in ['hello', 'Hello!', 'HELLO.', 'Hello Hello', 'hello porsche', 'Oh, hello.']:
            with self.subTest(text=text):
                self.assertTrue(matches_hello(text))

    def test_not_substring_or_alias(self):
        for text in ['', None, 'yellow', 'helloworld', 'shelloworld', 'go on', '(static)', 'halo', 'hallo']:
            with self.subTest(text=text):
                self.assertFalse(matches_hello(text))


if __name__ == '__main__':
    unittest.main()
