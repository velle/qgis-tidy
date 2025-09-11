### .gitattributes

```
*.qgz diff=qgisproj
*.qgs diff=qgisproj
```

### git config, set up diff driver

```ini
[diff "qgisproj"]
    textconv = ~/a/qgis-tidy/git_scripts/qgis_textconv.sh
    cachetextconv = true
```

### Usage

```bash
QGIS_TEXTCONV=STRICT git diff masterprj.qgz   # shows normalized strict diff
QGIS_TEXTCONV=RELAXED git diff masterprj.qgz  # shows relaxed diff
git diff masterprj.qgz                        # shows "Binary files differ"
```

### Aliases

Add to .bashrc

```bash
alias qd=QGIS_TEXTCONV=STRICT git diff
alias qdlax=QGIS_TEXTCONV=LAX git diff
```

### Usage with aliases

```bash
qd masterprj.qgz          # shows normalized strict diff
qdlax masterprj.qgz       # shows relaxed diff
git diff masterprj.qgz
```

### Pre-commit

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
