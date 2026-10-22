"""Exploratory metrics abstain when acquisition history is not identifiable."""
import numpy as np
import pytest

from tools.analyze_km_stacking import compare


def test_coherent_scaled_single_hit_is_indistinguishable_from_identical_hit_sum():
    data = np.random.default_rng(51).normal(size=(4, 100))
    single_stronger_hit = 2 * data
    sum_of_two_identical_hits = data + data
    a = compare(data, single_stronger_hit, 1)
    b = compare(data, sum_of_two_identical_hits, 1)
    assert a == b
    assert a["median_correlation"] == pytest.approx(1)
    assert a["median_rms_ratio_current_over_previous"] == pytest.approx(2)
    assert a["stack_count_inferred"] is None


def test_dead_channels_do_not_create_similarity_or_stack_evidence():
    result = compare(np.ones((3, 100)), np.zeros((3, 100)), 1)
    assert result["valid_channel_count"] == 0
    assert result["median_correlation"] is None
    assert result["median_rms_ratio_current_over_previous"] is None
    assert result["stack_count_inferred"] is None


def test_mismatched_record_dimensions_are_not_silently_aligned():
    with pytest.raises(ValueError, match="formas iguales"):
        compare(np.zeros((3, 100)), np.zeros((3, 90)), 1)
