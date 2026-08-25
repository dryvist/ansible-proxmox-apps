"""An absent seed slice drops its job from the run, and says so.

seed_sources.yml supports a partial bundle and promises that existing Nautobot
objects of an absent kind are retained. Running the job anyway loads an empty
source adapter and DiffSync computes an all-`delete` diff, so that promise held
only because delete happens to be a no-op on these models. The runner therefore
drops a slice-backed job whose slice carries no rows.

Two failure shapes are pinned here: dropping a job whose slice IS populated
(seeding silently stops), and keeping one whose slice is empty (the slice is one
missing no-op away from being wiped). The skip must also be logged, and must not
fail the converge — a partial bundle is a supported mode, not an error.

The django/nautobot stubs come from nautobot_run_seed_jobs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path

from nautobot_run_seed_jobs import Recorder
from nautobot_run_seed_jobs import load as load_runner

CHECKS = 0


def check(condition, message: str) -> None:
    """assert, but counted — a suite that runs zero assertions exits 0 too."""
    global CHECKS
    CHECKS += 1
    assert condition, message


def load_runner_capturing(registered: bool = False):
    """Import the runner against the current bundle; returns (module, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        module = load_runner(Recorder(modern=True), registered=registered)
    return module, buf.getvalue()


def main() -> None:
    original = os.environ.get("NAUTOBOT_SEED_FILE")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "seed.json"
        os.environ["NAUTOBOT_SEED_FILE"] = str(path)
        try:
            module, _ = load_runner_capturing()
            slices = dict(module.SLICE_JOBS)
            check(
                set(slices) == {"nodes", "reservations", "devices", "drives"},
                f"the slice-to-job map drifted: {sorted(slices)}",
            )

            for slice_name, job_name in slices.items():
                # Populated: the job runs, and is not reported as skipped.
                path.write_text(json.dumps({slice_name: [{"name": "x"}]}))
                module, out = load_runner_capturing()
                check(
                    job_name in module.SEED_JOBS,
                    f"{slice_name!r} carries a row but {job_name!r} was dropped — "
                    "that slice silently stops being seeded",
                )
                check(
                    "JOB_SKIPPED %s empty-source" % job_name not in out,
                    f"{job_name!r} was logged as skipped while its slice was populated",
                )

                # Empty, and absent entirely, must behave identically.
                for payload, label in (({slice_name: []}, "empty"), ({}, "absent")):
                    path.write_text(json.dumps(payload))
                    module, out = load_runner_capturing()
                    check(
                        job_name not in module.SEED_JOBS,
                        f"{slice_name!r} is {label} but {job_name!r} still runs — it "
                        "syncs against an empty source, one missing delete no-op "
                        "away from wiping the slice",
                    )
                    check(
                        "JOB_SKIPPED %s empty-source" % job_name in out,
                        f"{slice_name!r} {label}: the drop was not logged. Output: {out!r}",
                    )

            # A missing bundle drops every slice-backed job and logs each one.
            path.unlink(missing_ok=True)
            module, out = load_runner_capturing()
            for job_name in slices.values():
                check(
                    job_name not in module.SEED_JOBS,
                    f"{job_name!r} runs against a bundle that does not exist",
                )
                check("JOB_SKIPPED %s empty-source" % job_name in out, f"{job_name}: unlogged")

            # An intentional skip must not fail the converge: with every
            # remaining job registered and succeeding, an empty bundle still
            # has to exit 0. Routing the skip through run_one() — whose
            # not-registered path returns False — would exit 1 here.
            path.write_text(json.dumps({}))
            module, out = load_runner_capturing(registered=True)
            check(
                module.TEST_EXIT_CODE == 0,
                "an empty bundle exited %r; intentional skips must not fail the "
                "converge, or the supported partial-bundle mode is unusable. "
                "Output: %r" % (module.TEST_EXIT_CODE, out),
            )
            check(
                "JOB_DONE Seed VLANs and Prefixes SUCCESS" in out,
                "the non-slice-backed jobs did not run: %r" % out,
            )

            # The gate must never drop a job that is not slice-backed.
            check(
                "Seed VLANs and Prefixes" in module.SEED_JOBS,
                "a job with no slice in the map was dropped by the slice gate",
            )
            check(
                "Seed Hardware Inventory" in module.SEED_JOBS,
                "a plain job was dropped by the slice gate",
            )
        finally:
            if original is None:
                os.environ.pop("NAUTOBOT_SEED_FILE", None)
            else:
                os.environ["NAUTOBOT_SEED_FILE"] = original

    print("nautobot seed slice gate: OK (%d assertions)" % CHECKS)


if __name__ == "__main__":
    main()
