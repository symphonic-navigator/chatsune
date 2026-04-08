#!/bin/sh
# Runtime env var injection for the Vite-built SPA.
#
# Vite bakes `import.meta.env.VITE_*` values into the JS bundle at build time,
# so we can't set them per-environment via Docker env vars directly. Workaround:
# the build stage uses literal placeholders (__VITE_API_URL__, __VITE_WS_URL__)
# as the "values", and this script rewrites them to real values at container
# startup, just before nginx serves anything.
#
# To add a new VITE_* var:
#   1. Add `ENV VITE_FOO=__VITE_FOO__` to the build stage in Dockerfile
#   2. Append `VITE_FOO` to the VARS list below
set -eu

ROOT_DIR=/usr/share/nginx/html

# VITE_* vars the frontend reads at runtime. Grep src for `import.meta.env.VITE_`
# to find all of them.
VARS="VITE_API_URL VITE_WS_URL"

for var in $VARS; do
    value=$(printenv "$var" || true)
    placeholder="__${var}__"
    # `|` as sed delimiter avoids escaping slashes in URLs. URL-encoded `|` is
    # `%7C`, so real URL values should not contain a literal `|`.
    find "$ROOT_DIR" -type f \( -name '*.js' -o -name '*.html' -o -name '*.css' \) \
        -exec sed -i "s|${placeholder}|${value}|g" {} +
done
