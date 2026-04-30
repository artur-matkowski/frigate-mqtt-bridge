#!/usr/bin/env bash
# Convenience: only Frigate's topics (filters out other tenants on the broker).
exec "$(dirname "$0")/sniff.sh" 'frigate/#'
