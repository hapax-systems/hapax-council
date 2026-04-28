"""Mail-monitor — Gmail + omg.lol category-routing daemon.

Spec: ``docs/specs/2026-04-25-mail-monitor.md``.

Cascade slot 002: OAuth bootstrap + refresh-token loader. Subsequent
slots ship label/filter bootstrap, Pub/Sub watch + renewal, webhook
receivers, classifier, six per-purpose processors.

The daemon enforces a minimal Gmail scope pair and a server-side
``Hapax/*`` label-filter regime so the operator's full mailbox never
enters Hapax's read path. ``gmail.settings.basic`` is used only for
installing the server-side filters; ``gmail.modify`` covers labels,
watch renewal, and Hapax-labelled message handling.
"""
