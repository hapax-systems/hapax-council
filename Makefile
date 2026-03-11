.PHONY: install-systemd check-systemd-drift setup-ingest-venv

# Install systemd units and watchdog scripts from repo to system locations.
# Run after pulling changes or modifying units in systemd/.
install-systemd:
	@echo "Installing systemd units..."
	cp systemd/units/*.service systemd/units/*.timer ~/.config/systemd/user/
	@echo "Installing watchdog scripts..."
	cp systemd/watchdogs/*-watchdog ~/.local/bin/
	chmod +x ~/.local/bin/*-watchdog
	@echo "Reloading systemd..."
	systemctl --user daemon-reload
	@echo "Done. Run 'systemctl --user list-timers' to verify."

# Check if deployed units match repo (non-destructive).
check-systemd-drift:
	@drift=0; \
	for f in systemd/units/*.service systemd/units/*.timer; do \
		deployed="$$HOME/.config/systemd/user/$$(basename $$f)"; \
		if [ -f "$$deployed" ]; then \
			if ! diff -q "$$f" "$$deployed" > /dev/null 2>&1; then \
				echo "DRIFT: $$f differs from $$deployed"; \
				drift=1; \
			fi; \
		else \
			echo "MISSING: $$deployed not deployed"; \
			drift=1; \
		fi; \
	done; \
	for f in systemd/watchdogs/*-watchdog; do \
		deployed="$$HOME/.local/bin/$$(basename $$f)"; \
		if [ -f "$$deployed" ]; then \
			if ! diff -q "$$f" "$$deployed" > /dev/null 2>&1; then \
				echo "DRIFT: $$f differs from $$deployed"; \
				drift=1; \
			fi; \
		else \
			echo "MISSING: $$deployed not deployed"; \
			drift=1; \
		fi; \
	done; \
	if [ "$$drift" -eq 0 ]; then \
		echo "No drift detected — repo matches deployed."; \
	else \
		exit 1; \
	fi

# Create isolated venv for rag-ingest (docling conflicts with pydantic-ai on huggingface-hub).
setup-ingest-venv:
	@echo "Creating .venv-ingest..."
	uv venv --python 3.12 .venv-ingest
	uv pip install --python .venv-ingest/bin/python \
		"docling>=2.75.0" "ollama>=0.6.1" "watchdog>=6.0.0" "qdrant-client>=1.17.0"
	@echo "Done. Restart rag-ingest: systemctl --user restart rag-ingest.service"
