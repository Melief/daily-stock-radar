#!/usr/bin/env python3
"""Fetch the Blue Sky Finviz screener into its separate DSR source CSV."""
from pathlib import Path

import test_finviz

test_finviz.CONFIG_FILE = Path("blue_sky_url.txt")
test_finviz.OUTPUT_FILE = Path("data/blue_sky_tickers.csv")
test_finviz.SOURCE_NAME = "Blue Sky"

if __name__ == "__main__":
    raise SystemExit(test_finviz.main())
