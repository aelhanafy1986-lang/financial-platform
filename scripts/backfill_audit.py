# -*- coding: utf-8 -*-
"""Backfill quality-gate audit records for legacy analysis rows.

Runs the central auditor (app/audit.py run_quality_gate) in **check-only**
mode (apply_repairs=False) over every stored analysis that lacks an audit
record, then writes back the result_json with ONLY the ``audit`` key added.
Stored figures are never modified — verified per row before the write by
comparing the parsed JSON minus the audit key against the original, and
re-verified from the database afterwards.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import sys

sys.path.insert(0, ".")
from app.audit import run_quality_gate  # noqa: E402

DB = "financial.db"


def strip_audit(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "audit"}


def main() -> None:
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT id, filename, result_json FROM analyses ORDER BY id"
    ).fetchall()

    updated, skipped_have, skipped_empty = [], [], []
    originals: dict[int, dict] = {}

    for rid, filename, rj in rows:
        if not rj:
            skipped_empty.append(rid)
            continue
        res = json.loads(rj)
        if isinstance(res, dict) and isinstance(res.get("audit"), dict):
            skipped_have.append(rid)
            continue
        if not isinstance(res, dict):
            skipped_empty.append(rid)
            continue

        # check-only assessment on a deep copy — nothing here touches the DB
        candidate = copy.deepcopy(res)
        report = run_quality_gate(candidate, apply_repairs=False)
        audit_record = candidate.get("audit")

        # merged = original + audit key only
        merged = dict(res)
        merged["audit"] = audit_record

        # HARD GUARANTEE: parsed numbers/metadata identical minus the audit key
        assert strip_audit(merged) == res, f"id={rid}: non-audit content drifted"
        assert audit_record.get("mode") == "check_only", f"id={rid}: wrong mode"
        originals[rid] = res
        updated.append((rid, filename, report, audit_record))
        con.execute(
            "UPDATE analyses SET result_json = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), rid),
        )

    con.commit()

    print(f"updated : {len(updated)} rows")
    print(f"skipped (already audited): {len(skipped_have)} -> {skipped_have}")
    print(f"skipped (no result)      : {len(skipped_empty)} -> {skipped_empty}")
    print()
    for rid, filename, report, audit_record in updated:
        warns = [i["code"] for i in audit_record.get("warnings", [])]
        errs = [i["code"] for i in audit_record.get("errors", [])]
        reps = [i["code"] for i in audit_record.get("repairs", [])]
        verdict = "GREEN" if audit_record["ok"] else (
            "RED" if errs else "AMBER")
        print(
            f"  id={rid:>2} [{verdict:>5}] errors={errs} warnings={warns} "
            f"repairs-applied={reps} (figs untouched)"
        )

    # ---- post-write verification, read back from the database --------------
    print("\npost-write verification (from DB):")
    total_audited = 0
    for rid in [r[0] for r in rows]:
        rj = con.execute(
            "SELECT result_json FROM analyses WHERE id=?", (rid,)
        ).fetchone()[0]
        if not rj:
            continue
        res = json.loads(rj)
        if not isinstance(res, dict) or not isinstance(res.get("audit"), dict):
            print(f"  FAIL id={rid}: audit record missing")
            continue
        total_audited += 1
        if rid in originals:
            assert strip_audit(res) == originals[rid], (
                f"id={rid}: stored figures changed!"
            )
    print(f"  all {total_audited}/{len(rows)} rows now carry an audit record")
    print(f"  number-preservation verified for {len(originals)} backfilled rows")
    con.close()


if __name__ == "__main__":
    main()
