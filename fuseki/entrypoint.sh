#!/bin/sh
# Serve whichever graphs the builder wrote, and refuse to start without any.
#
# The set of sources is a choice made at build time, so the assembler config
# cannot be a fixed file: it is written here from what the last build says it
# wrote. An empty endpoint answers every query with zero rows and looks like a
# working server that disagrees with the tests, which is the failure worth
# preventing.
set -eu

DATA=${DATA_DIR:-/data}
CONFIG=/fuseki/run-config.ttl
MANIFEST="$DATA/manifest.json"

# The manifest names the graphs this build produced, and it is the authority.
# Reading the directory instead serves every .ttl an earlier build happened to
# leave behind, which does not fail: the extra graphs answer alongside the
# intended ones, so a ward appears twice and a query over 7,265 places returns
# 88,013. A graph nobody asked for is harder to notice than a missing one.
if [ -f "$MANIFEST" ]; then
  FILES=""
  for name in $(grep -o '"ttl_file": "[^"]*"' "$MANIFEST" | cut -d'"' -f4); do
    if [ ! -f "$DATA/$name" ]; then
      echo "manifest names $name but $DATA/$name is not there." >&2
      echo "Run the builder again; the two disagree about what was built." >&2
      exit 1
    fi
    FILES="$FILES $DATA/$name"
  done
else
  FILES=$(find "$DATA" -maxdepth 1 -name '*.ttl' | sort)
fi

if [ -z "$FILES" ]; then
  echo "nothing to serve from $DATA. Run the builder first:" >&2
  echo "  docker compose run --rm builder" >&2
  exit 1
fi

{
  cat /fuseki/config-head.ttl
  for f in $FILES; do
    echo "    ja:data \"file://$f\" ;"
  done
  echo "    ."
} > "$CONFIG"

echo "serving:"
for f in $FILES; do
  echo "  $(basename "$f")  $(wc -c < "$f") bytes"
done
if [ -f "$DATA/manifest.json" ]; then
  echo "licence: $(grep -o '"name": "[^"]*"' "$DATA/manifest.json" | tail -1 | cut -d'"' -f4)"
fi

exec java \
  -Dfile.encoding=UTF-8 \
  -XX:MaxRAMPercentage=${MAX_RAM_PERCENT:-60} \
  -jar /fuseki/fuseki-server.jar \
  --config="$CONFIG" \
  --port=3030
