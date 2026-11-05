import pytest

from cron_consolidator import cronfields as cf


def test_fixed_time():
    m, h, dom, mon, dow = cf.parse("30 8 * * *")
    assert m == {30} and h == {8} and len(dom) == 31 and len(mon) == 12 and len(dow) == 7


def test_lists_ranges_steps_and_names():
    assert cf.parse("*/15 * * * *")[0] == {0, 15, 30, 45}
    assert cf.parse("0 9-11 * * *")[1] == {9, 10, 11}
    assert cf.parse("0 8,20 * * *")[1] == {8, 20}
    assert cf.parse("0 9 * * mon-fri")[4] == {1, 2, 3, 4, 5}
    assert cf.parse("0 9 * jan,mar *")[3] == {1, 3}


def test_sunday_is_zero_or_seven():
    assert cf.parse("0 9 * * 7")[4] == {0}
    assert cf.parse("0 9 * * 0")[4] == {0}
    assert cf.parse("0 9 * * 5-7")[4] == {5, 6, 0}


def test_overlap_known_good_and_bad():
    nine = cf.parse("0 9 * * *")
    assert cf.overlap(nine, cf.parse("0 9 * * mon"))
    assert cf.overlap(nine, cf.parse("*/30 * * * *"))
    assert not cf.overlap(nine, cf.parse("1 9 * * *"))
    assert not cf.overlap(cf.parse("0 9 * * mon"), cf.parse("0 9 * * tue"))


def test_fires_per_day():
    assert cf.fires_per_day(cf.parse("0 9 * * *")) == pytest.approx(1)
    assert cf.fires_per_day(cf.parse("*/30 * * * *")) == pytest.approx(48)
    assert cf.fires_per_day(cf.parse("0 9 * * mon")) == pytest.approx(1 / 7)


@pytest.mark.parametrize("bad", ["", "* * * *", "61 * * * *", "* 24 * * *", "0 9 * * 8", "*/0 * * * *",
                                 "0 9 * foo *", "0 9 5-2 * *"])
def test_rejects_what_it_cannot_read(bad):
    with pytest.raises((ValueError, KeyError)):
        cf.parse(bad)
