"""hapax.omg.lol web page builder + publisher (ytb-OMG2).

Phase 1: static HTML at ``static/index.html`` (PR #1312).
Phase 1.5 (this module): ``publisher.py`` reads the HTML and POSTs to
``omg.lol`` via :class:`shared.omg_lol_client.OmgLolClient`.

Phase 2 (deferred): Jinja2 template + dynamic rebuilder + systemd timer.
"""
