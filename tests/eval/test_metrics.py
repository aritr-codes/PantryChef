from pantrychef.eval.metrics import hit_rate, makeable_at_k, mrr_at_k, recall_at_k

L = ["a", "b", "c", "d"]


def test_recall_hit_and_miss():
    assert recall_at_k(L, "b", 2) == 1.0
    assert recall_at_k(L, "c", 2) == 0.0
    assert recall_at_k(L, "d", 4) == 1.0


def test_recall_edges():
    assert recall_at_k(L, "d", 100) == 1.0  # k larger than the list
    assert recall_at_k(L, "zzz", 10) == 0.0  # gold missing
    assert recall_at_k(L, "a", 0) == 0.0
    assert recall_at_k(L, "a", -3) == 0.0
    assert recall_at_k([], "a", 10) == 0.0


def test_mrr_hand_computed():
    assert mrr_at_k(L, "a", 10) == 1.0
    assert mrr_at_k(L, "d", 10) == 0.25  # rank 4
    ranked = [str(i) for i in range(1, 13)]
    assert mrr_at_k(ranked, "10", 10) == 0.1  # rank 10 is inside k
    assert mrr_at_k(ranked, "11", 10) == 0.0  # rank 11 is outside k
    assert mrr_at_k(ranked, "4", 3) == 0.0


def test_mrr_edges_and_ties():
    assert mrr_at_k(L, "zzz", 10) == 0.0
    assert mrr_at_k(L, "a", 0) == 0.0
    assert mrr_at_k(L, "a", -1) == 0.0
    assert mrr_at_k([], "a", 10) == 0.0
    assert mrr_at_k(["x", "g", "g"], "g", 10) == 0.5  # repeated id: first rank counts
    assert mrr_at_k(L, "d", 99) == 0.25  # k larger than the list


HT = [(2, 2), (1, 3), (3, 3), (0, 1)]


def test_makeable_at_k():
    assert makeable_at_k(HT, 1) == 1.0
    assert makeable_at_k(HT, 3) == 2 / 3
    assert makeable_at_k(HT, 10) == 0.5  # k larger than the list: divide by 4
    assert makeable_at_k(HT, 0) == 0.0
    assert makeable_at_k(HT, -1) == 0.0
    assert makeable_at_k([], 5) == 0.0
    assert makeable_at_k([(1, 2), (0, 2)], 2) == 0.0


def test_hit_rate():
    assert hit_rate(HT) == 1.0
    assert hit_rate([(1, 2), (0, 3)]) == 0.0
    assert hit_rate([]) == 0.0
    assert hit_rate([(0, 1)] * 5 + [(2, 2)]) == 1.0
