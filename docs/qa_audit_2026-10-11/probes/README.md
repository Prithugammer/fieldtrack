# Audit probes

Scripts used to produce the files in `../evidence/`. They are read-only with respect to the application
source: they import the backend, build throw-away in-memory (or scratch-file) databases, and print results.

* Run from the `backend/` directory with its virtualenv Python, with `DATABASE_URL` cleared for that process.
* Replace the `<SCRATCH_DIR>` placeholder with any writable folder (it holds the helper module and scratch DB files).
* `probe_common.py` is the shared helper; `probe_a…i` correspond to evidence files A…I; `diff_probe.py` +
  `compare_out.py` perform the old-vs-new differential test (extract the old tree first with
  `git archive 67d9214 backend -o old.tar`); `probe_farsite_run.py LAT LNG` and `probe_profile.py` reproduce D-02.
* The 32-character key inside `probe_d_run.py` is a throw-away test constant, not a real secret.