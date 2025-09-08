
# qgis-tidy

Normalize QGIS project files (`.qgs` and `.qgz`) for stable, meaningful diffs.

## Install
- Requires Python 3.8+ and `lxml`:
  ```bash
  pip install lxml
  ```
- Save `qgis-tidy.py` somewhere on your `PATH` (or run via `python qgis-tidy.py`).

## Usage
```bash
# Preview normalized XML to stdout
qgis-tidy project.qgs

# In-place for .qgs
qgis-tidy -i project.qgs

# In-place for .qgz (normalizes embedded .qgs, re-zips deterministically)
qgis-tidy -i project.qgz

# Also normalize extra XML entries inside the archive (e.g., styles)
qgis-tidy -i --include-xml "*.qml,*.sld" project.qgz

# Dry-run to check if a file would change (exit 1 if yes)
qgis-tidy --dry-run project.qgs
qgis-tidy --dry-run project.qgz

# For .qgz, list entries
qgis-tidy --list project.qgz
```

## Git integration (diff-time)
`.gitattributes`:
```
*.qgs diff=qgistry
*.qgz diff=qgztry
```

Git config:
```ini
[diff "qgistry"]
    textconv = sh -c 'qgis-tidy "$1" 2>/dev/null || cat "$1"'

[diff "qgztry"]
    textconv = sh -c 'unzip -p "$1" "*.qgs" 2>/dev/null | qgis-tidy || unzip -p "$1" "*.qgs"'
```

## Pre-commit (recommended)
`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: local
    hooks:
      - id: qgis-tidy-qgs
        name: qgis-tidy (.qgs)
        entry: qgis-tidy -i
        language: system
        files: \.qgs$

      - id: qgis-tidy-qgz
        name: qgis-tidy (.qgz)
        entry: qgis-tidy -i --include-xml "*.qml,*.sld"
        language: system
        files: \.qgz$
        pass_filenames: true
```

## Rules and customization
- Built-in defaults strip some volatile attributes and sort a few order-insensitive lists.
- You can extend with a YAML file:
  ```yaml
  strip_attributes:
    - expanded
    - selected
    - timestamp

  sort_rules:
    - parent_xpath: //renderer-v2/categorizedSymbol
      child_xpath: category
      key_xpath:   @label
  ```
  Then:
  ```bash
  qgis-tidy -i --config rules.yaml project.qgs
  qgis-tidy -i --config rules.yaml project.qgz
  ```

## Notes
- Non-XML entries (e.g., `.qgd`) are copied verbatim.
- The `.qgz` repack uses fixed timestamps and sorted entries for stability.
- Exact byte-for-byte identity across different platforms isn't guaranteed due to zlib differences, but is generally stable within a team/toolchain.
