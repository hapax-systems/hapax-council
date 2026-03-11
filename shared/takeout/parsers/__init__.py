"""Takeout service parsers.

Each parser module exports a parse() function:
    parse(zf: ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]
"""
