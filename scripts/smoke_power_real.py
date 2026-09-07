"""Smoke real (sem mocks): aplica 10/18, confere hex, libera, restaura original."""
import sys

sys.path.insert(0, "D:/Projetos/TurboCore/src")

from turbocore import power

original = power.query_current_percent()
print("ORIGINAL_CPMAXCORES =", original)

pct = power.apply_core_limit(chosen_cores=10, physical_cores=18)
print("APPLIED_PCT =", pct)
assert pct == 56, pct
now = power.query_current_percent()
print("QUERY_APOS_10_CORES =", now)
assert now == 56, now

power.release_all_cores()
now = power.query_current_percent()
print("QUERY_APOS_RELEASE =", now)
assert now == 100, now

power.apply_percent(original)
now = power.query_current_percent()
print("RESTORED =", now)
assert now == original, (now, original)
print("SMOKE_POWER_OK")
