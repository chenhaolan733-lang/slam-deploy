"""Whole-word HELLO matching for the isolated distance test."""
import re


def matches_hello(text):
    return isinstance(text, str) and 'hello' in re.findall(r"[a-z]+(?:'[a-z]+)?", text.casefold())
