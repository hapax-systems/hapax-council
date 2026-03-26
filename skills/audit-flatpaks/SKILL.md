---
name: audit-flatpaks
description: Audit installed flatpak apps and find native alternatives. Auto-run when: storage-audit reveals large flatpak usage, operator mentions app performance issues related to sandboxing, or user asks about flatpaks. Invoke proactively without asking.
---

Audit flatpak installations and find native package alternatives.

```bash
flatpak list --app --columns=name,application,version,size 2>/dev/null || echo "No flatpaks installed"
```

```bash
du -sh ~/.var/app/*/ 2>/dev/null | sort -rh | head -15
```

```bash
flatpak list --app --columns=application 2>/dev/null | while read app; do
  name=$(echo "$app" | rev | cut -d. -f1 | rev | tr '[:upper:]' '[:lower:]')
  native=$(paru -Ss "^${name}$" 2>/dev/null | head -1)
  if [ -n "$native" ]; then
    echo "NATIVE AVAILABLE: $app -> $native"
  fi
done
```

For each flatpak with a native alternative:
- Compare version (flatpak vs native)
- Note disk savings (flatpak runtime overhead)
- Offer to install native with `paru -S <package>` and remove flatpak with `flatpak uninstall <app>`
- Warn about data migration for apps storing config in `~/.var/app/`
