"""router/orders.py: the order-relevance gate (§5.4).

`llm_allowed` is the one function this whole module protects - every test here is really
asking "would this filing be allowed to reach an LLM or OCR call", because that is the
question the rest of src/tradebot/orders/ is built never to answer on its own.
"""

from __future__ import annotations

from tradebot.router.orders import classify, in_scope, llm_allowed, refine_with_body


def test_order_win_category_is_order_related():
    r = classify("Bagging/Receiving of orders/contracts", "Skipper Limited order update")
    assert r.bucket == "order_win"
    assert r.order_related is True
    assert llm_allowed(r) is True
    assert in_scope(r) is True


def test_order_win_with_sub_para_suffix_still_matches():
    r = classify("Bagging/Receiving of orders/contracts (Sub-para 4-Para B)", "x")
    assert r.bucket == "order_win"
    assert r.order_related is True


def test_order_candidate_category_is_order_related():
    r = classify("Awarding of order(s)/contract(s)", "BEML has awarded a contract")
    assert r.bucket == "order_candidate"
    assert r.order_related is True


def test_red_flag_never_order_related_despite_the_word_order():
    r = classify("Action(s) taken or orders passed", "orders passed by NCLT")
    assert r.bucket == "red_flag"
    assert r.order_related is False
    assert llm_allowed(r) is False


def test_out_of_scope_category_is_never_downloaded_or_sent_to_llm():
    r = classify("Trading Window", "Closure of Trading Window")
    assert r.bucket == "out_of_scope"
    assert r.order_related is False
    assert in_scope(r) is False
    assert llm_allowed(r) is False


# --------------------------------------------------------------------- catch_all + headline

def test_catch_all_with_headline_keyword_is_order_related():
    r = classify("Press Release", "Company secures a work order worth Rs 220 crore")
    assert r.bucket == "catch_all"
    assert r.order_related is True
    assert in_scope(r) is True


def test_catch_all_with_no_keyword_is_not_order_related_but_still_in_scope():
    r = classify("General Updates", "Company has informed the Exchange about General Updates")
    assert r.bucket == "catch_all"
    assert r.order_related is False
    assert in_scope(r) is True   # still downloaded (widened D7), just no OCR/LLM yet
    assert llm_allowed(r) is False


def test_catch_all_headline_suppress_term_wins_over_a_positive_word():
    r = classify("General Updates", "Action(s) taken or orders passed by the Income Tax dept")
    assert r.order_related is False


def test_bare_order_in_headline_still_counts_positive_without_a_suppress_hit():
    # §5.4's keyword list includes bare "order"/"contract" on the headline (not the body,
    # where "in order to" would flood it) - a short headline saying just "order" is rare
    # enough, and specific enough, to trust.
    r = classify("Updates", "Company Receives Order from Ministry of Defence")
    assert r.order_related is True


# --------------------------------------------------------------------- body refinement

def test_body_keyword_flips_a_catch_all_with_a_generic_headline():
    # The HILINFRA case (§5.4): a real order win filed as a Press Release with a generic
    # headline, findable only in the body.
    r = classify("Press Release", "Company has informed the Exchange about General Updates")
    assert r.order_related is False
    body = "We are pleased to announce receipt of a Letter of Award for a toll contract."
    refined = refine_with_body(r, body)
    assert refined.order_related is True
    assert llm_allowed(refined) is True


def test_bare_order_in_body_text_does_not_flip_relevance():
    # "in order to" and similar prose must not trigger - only the stronger body phrases do.
    r = classify("General Updates", "General Updates")
    body = "In order to comply with the regulation, the company files this update."
    refined = refine_with_body(r, body)
    assert refined.order_related is False


def test_refine_with_body_never_changes_an_already_order_related_filing():
    r = classify("Bagging/Receiving of orders/contracts", "x")
    refined = refine_with_body(r, "nothing relevant here")
    assert refined is r


def test_refine_with_body_never_applies_to_red_flag_or_order_win_buckets():
    r = classify("Action(s) taken or orders passed", "orders passed")
    refined = refine_with_body(r, "we received a letter of award worth Rs 10 crore")
    assert refined.order_related is False
    assert refined.bucket == "red_flag"
