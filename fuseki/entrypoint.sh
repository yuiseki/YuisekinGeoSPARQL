#!/bin/sh
# Serve whichever graphs the builder wrote, and refuse to start without any.
#
# The set of sources is a choice made at build time, so the assembler config
# cannot be a fixed file: it is written here from what is actually on disk. An
# empty endpoint answers every query with zero rows and looks like a working
# server that disagrees with the tests, which is the failure worth preventing.
set -eu

DATA=${DATA_DIR:-/data}
CONFIG=/fuseki/run-config.ttl

FILES=$(find "$DATA" -maxdepth 1 -name '*.ttl' | sort)
if [ -z "$FILES" ]; then
  echo "no .ttl in $DATA. Run the builder first:" >&2
  echo "  docker compose run --rm builder --source all" >&2
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
