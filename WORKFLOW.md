# What goes in pre-commit

- set project-settings.yaml
- qgis-tidy
    - run CELMO
    - run c14n
    - run pretty-print

# What goes in standard/strict diff

- qgis-tidy
    - run CELMO
    - run c14n
    - run pretty-print

# What goes in lax diff

- qgis-strip (strips selected attributes)
- qgis-tidy
    - run CELMO
    - run c14n
    - run pretty-print
