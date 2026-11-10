"""Feature flags for rulings that depart from AP_POLICY.md v3.2 (see submission/RULINGS.md).

Every flag is OFF by default, so the default behaviour is the written policy. Switch one on with
LEDGERLINE_FLAG_<NAME>=1. Flags are read at call time, so a test or a batch run can set them per process.
"""
from __future__ import annotations

import os

# disp_05. A line whose quantity x unit price differs from its printed amount by more than ₹1.00 needs review.
# New reason code: line_arithmetic_mismatch.
LINE_ARITHMETIC = "LINE_ARITHMETIC"

# disp_06. An invoice dated after the day we received it needs review, and vendor_new is judged on the earlier
# of the printed date and the received date, so a post-dated invoice can't age a new vendor past 90 days.
# New reason code: date_after_receipt.
DATE_AFTER_RECEIPT = "DATE_AFTER_RECEIPT"

# disp_04. suspicious_content needs text that addresses automated systems *and* tries to steer how the document
# is processed (approval, checks, bank details and so on), or markup. Merely mentioning "your automation
# system" isn't enough. No new reason code; this narrows an existing one.
NARROW_SUSPICIOUS = "NARROW_SUSPICIOUS"

ALL_FLAGS = (LINE_ARITHMETIC, DATE_AFTER_RECEIPT, NARROW_SUSPICIOUS)


def enabled(name: str) -> bool:
    return os.getenv(f"LEDGERLINE_FLAG_{name}", "").strip().lower() in {"1", "true", "yes", "on"}
