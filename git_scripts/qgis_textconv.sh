#!/bin/sh
#qgis_textconv.sh
set -eu

case "${QGIS_TEXTCONV-}" in
    STRICT)     exec qgis-tidy -o - "$@" ;;
    LAX)        exec qgis-tidy -o - --lax "$@" ;;
    *)          exit 0 ;;  # no conversion → Git shows "Binary files differ"
esac
