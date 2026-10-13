import pytest

from turbocore.effective_clock import CounterReading, EffectiveClockSampler, effective_mhz


def test_actual_cycles_are_averaged_over_the_complete_interval():
    # 750 million actual cycles over a complete second => 750 effective MHz,
    # regardless of an instantaneous active clock of e.g. 3800 MHz.
    before = CounterReading(100, 100, 10)
    after = CounterReading(750_000_100, 500_000_100, 11)
    assert effective_mhz(before, after) == 750
    assert effective_mhz(before, CounterReading(100, 100, 11)) == 0


@pytest.mark.parametrize("after", [
    CounterReading(1000, 1000, 10.001),
    CounterReading(1000, 1000, 30),
    CounterReading(9, 1000, 11),
    CounterReading(1000, 9, 11),
])
def test_reset_rollover_and_stale_windows_are_reprimed(after):
    assert effective_mhz(CounterReading(10, 10, 10), after) is None


def test_physical_core_includes_its_busy_smt_sibling():
    ticks = {0: CounterReading(100, 100, 10),
             1: CounterReading(100, 100, 10)}
    sampler = EffectiveClockSampler([[0, 1]], ticks.__getitem__)
    assert sampler.sample(100) is None
    ticks[0] = CounterReading(100, 100, 11)  # first logical thread slept
    ticks[1] = CounterReading(500_000_100, 250_000_100, 11)
    clock = sampler.sample(100)[0]
    assert clock.mhz == 500
    assert clock.ratio == 5


def test_pause_does_not_display_a_long_historical_average():
    ticks = {0: CounterReading(100, 100, 10)}
    sampler = EffectiveClockSampler([[0]], ticks.__getitem__)
    assert sampler.sample(100) is None
    ticks[0] = CounterReading(1_000_000_100, 1_000_000_100, 30)
    assert sampler.sample(100) is None
    ticks[0] = CounterReading(1_200_000_100, 1_100_000_100, 31)
    assert sampler.sample(100)[0].mhz == 200
