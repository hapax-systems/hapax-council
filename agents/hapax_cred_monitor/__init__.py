"""Credential watch + auto-prep daemon.

Detects which expected credential entries are present or missing in the
operator's password store and emits an operator-unblockers report so
gated work surfaces cleanly. The monitor never reads, decrypts, prints,
or logs secret values — it operates exclusively on entry NAMES (the
``.gpg`` filenames under ``~/.password-store/``).

See ``agents/hapax_cred_monitor/registry.py`` for the
entry-name → unblocked-services mapping; ``monitor.py`` for snapshot
and delta computation; ``unblocker_report.py`` for the JSON state
file the operator dashboards consume.
"""
