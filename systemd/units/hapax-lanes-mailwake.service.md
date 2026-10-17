# Staged unit source: the .md suffix is excluded by existing deployers.
# After separate admission, install these bytes as hapax-lanes-mailwake.service.
[Unit]
Description=Hapax bounded lane mailbox wake loop
# Replaces the preserved transient v2 only after separately admitted installation.

[Service]
Type=simple
ExecStart=%h/.cache/hapax/source-activation/worktree/systemd/scripts/hapax-lanes-mailwake
Restart=on-failure
RestartSec=5
TimeoutStopSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hapax-lanes-mailwake
# No automatic activation: retain the staged filename until release admission.
