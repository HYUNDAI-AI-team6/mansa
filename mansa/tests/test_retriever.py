import unittest
from functools import partial

from core.schemas import Intent, ScoredChunk
from features.master.taxonomy import TaxonomyService
from features.retrieval.retriever import (
    MANUAL_COLLECTION,
    MANUAL_DOC_TYPE,
    SAFETY_COLLECTION,
    SAFETY_DOC_TYPE,
    chunk_tags,
    default_safety_terms,
    distance_to_similarity,
    load_corpus,
    merge_evidence,
    rank_by_tags,
    rank_ids,
    search_manual,
    search_safety,
)

MANUAL = [
    {"id": "m.pdf:p1:0", "text": "브레이크 패드 교체 절차", "metadata": {"source": "m.pdf", "page": 1}},
    {"id": "m.pdf:p2:0", "text": "엔진 오일 교체 주기", "metadata": {"source": "m.pdf", "page": 2}},
    {"id": "m.pdf:p3:0", "text": "유압 호스 점검", "metadata": {"source": "m.pdf", "page": 3}},
]
SAFETY = [
    {"id": "s.pdf:p1:0", "text": "크레인 작업반경 내 출입을 금지한다.", "metadata": {"source": "s.pdf", "page": 1}},
    {"id": "s.pdf:p2:0", "text": "붐 점검 전 전원을 차단한다.", "metadata": {"source": "s.pdf", "page": 2}},
]
TAGGED = [
    {"id": "a", "text": "유압 호스 교체", "metadata": {"part": "유압 호스", "task": "교체"}},
    {"id": "b", "text": "붐 각도 확인 방법", "metadata": {"part": "붐", "task": "점검"}},
    {"id": "c", "text": "붐 길이 표", "metadata": {"part": "붐, 와이어로프"}},
    {"id": "d", "text": "목차", "metadata": {}},
]
NO_TAGS = Intent(intent="procedure")
BOOM_CHECK = Intent(intent="procedure", parts=["붐"], task="점검")


def fake_search(hits):
    """search_chunks 대신 쓰는 가짜 함수. 정해진 hits를 돌려주고 받은 검색어·DB·컬렉션을 calls에 기록한다."""
    calls = []

    def search(query, doc_type, collection, top_k=5, where=None):
        calls.append((query, doc_type, collection))
        return hits

    search.calls = calls
    return search


class SearchManualTest(unittest.TestCase):
    def test_uses_manual_db(self):
        search = fake_search([])
        search_manual("브레이크", NO_TAGS, search, MANUAL)
        self.assertEqual(search.calls, [("브레이크", MANUAL_DOC_TYPE, MANUAL_COLLECTION)])

    def test_chunk_found_by_both_ranks_first(self):
        hits = [{**MANUAL[2], "distance": 0.4}, {**MANUAL[0], "distance": 0.6}]
        result = search_manual("브레이크 패드", NO_TAGS, fake_search(hits), MANUAL)
        self.assertEqual(result[0].chunk_id, "m.pdf:p1:0")  # 벡터 2등이지만 BM25에도 걸려서 1등

    def test_score_is_similarity_or_zero(self):
        hits = [{**MANUAL[2], "distance": 0.4}]
        result = {c.chunk_id: c for c in search_manual("브레이크", NO_TAGS, fake_search(hits), MANUAL)}
        self.assertAlmostEqual(result["m.pdf:p3:0"].score, 0.8)  # 1 - 0.4 / 2
        self.assertEqual(result["m.pdf:p1:0"].score, 0.0)  # BM25로만 찾음

    def test_keeps_text_metadata_and_doc_type(self):
        result = search_manual("오일", NO_TAGS, fake_search([]), MANUAL)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "엔진 오일 교체 주기")
        self.assertEqual(result[0].metadata, {"source": "m.pdf", "page": 2})
        self.assertEqual(result[0].doc_type, "tech")

    def test_chunk_only_in_vector_hits_does_not_break(self):
        # 미리 읽은 corpus에 없는(나중에 올라온) 청크가 벡터 결과에만 있어도 에러 없이 처리한다
        new = {"id": "new.pdf:p1:0", "text": "새 매뉴얼", "metadata": {"source": "new.pdf", "page": 1}, "distance": 0.2}
        result = search_manual("질문", NO_TAGS, fake_search([new]), MANUAL)
        self.assertEqual(result[0].chunk_id, "new.pdf:p1:0")
        self.assertEqual(result[0].text, "새 매뉴얼")

    def test_nothing_found(self):
        self.assertEqual(search_manual("크레인", NO_TAGS, fake_search([]), MANUAL), [])


class SearchSafetyTest(unittest.TestCase):
    def test_uses_safety_db_with_expanded_query(self):
        search = fake_search([])
        search_safety("각도 확인", BOOM_CHECK, search, SAFETY)
        self.assertEqual(search.calls, [("각도 확인 붐 점검", SAFETY_DOC_TYPE, SAFETY_COLLECTION)])

    def test_expanded_words_find_chunk_without_question_words(self):
        # 질문에는 "붐"·"점검"이 없지만 Intent로 보강한 단어가 BM25에 걸린다
        result = search_safety("각도 확인", BOOM_CHECK, fake_search([]), SAFETY)
        self.assertEqual([c.chunk_id for c in result], ["s.pdf:p2:0"])
        self.assertEqual(result[0].doc_type, "secure")

    def test_custom_expander(self):
        result = search_safety("크레인", NO_TAGS, fake_search([]), SAFETY, expand_terms=lambda _: ["작업반경"])
        self.assertEqual([c.chunk_id for c in result], ["s.pdf:p1:0"])


class TagTest(unittest.TestCase):
    def test_chunk_tags_reads_comma_separated_values(self):
        self.assertEqual(chunk_tags({"part": "붐, 와이어로프", "task": "점검"}), {"붐", "와이어로프", "점검"})

    def test_chunk_tags_ignores_missing_or_wrong_values(self):
        self.assertEqual(chunk_tags({}), set())
        self.assertEqual(chunk_tags({"part": 3, "task": ""}), set())

    def test_more_overlap_ranks_first_and_zero_is_excluded(self):
        self.assertEqual(rank_by_tags(BOOM_CHECK, TAGGED), ["b", "c"])  # b 2개, c 1개, a·d는 0개라 빠짐

    def test_no_overlap_or_no_intent_tags(self):
        self.assertEqual(rank_by_tags(Intent(intent="procedure", parts=["브레이크"]), TAGGED), [])
        self.assertEqual(rank_by_tags(NO_TAGS, TAGGED), [])

    def test_model_is_not_compared(self):
        # 모델은 태그 비교에 쓰지 않는다 (나중에 where 필터로 거른다)
        intent = Intent(intent="procedure", model_ids=["CR-100"])
        corpus = [{"id": "x", "text": "t", "metadata": {"part": "CR-100"}}]
        self.assertEqual(rank_by_tags(intent, corpus), [])

    def test_rank_ids_without_tags_keeps_old_behavior(self):
        hits = [{"id": "x"}, {"id": "y"}]
        self.assertEqual(rank_ids(hits, [("y", 1.0)]), rank_ids(hits, [("y", 1.0)], []))

    def test_tag_finds_chunk_missed_by_words(self):
        # 질문 단어("작업 순서")는 어느 본문과도 안 겹치지만 태그(붐·점검)로 찾는다
        result = search_manual("작업 순서", BOOM_CHECK, fake_search([]), TAGGED)
        self.assertEqual([c.chunk_id for c in result], ["b", "c"])
        self.assertEqual(result[0].score, 0.0)  # 벡터 유사도가 없어서 점수는 0이다 (알려진 한계)
    
    def test_chunk_tags_reads_list_values(self):
        self.assertEqual(chunk_tags({"part": ["붐", " 와이어로프 "], "task": ["점검"]}), {"붐", "와이어로프", "점검"})

    def test_chunk_tags_ignores_wrong_list_items(self):
        self.assertEqual(chunk_tags({"part": [3, ""], "task": []}), set())

class SafetyTermsTest(unittest.TestCase):
    def test_without_lookup_uses_parts_and_task(self):
        self.assertEqual(default_safety_terms(BOOM_CHECK), ["붐", "점검"])

    def test_lookup_terms_are_added_after_default_terms(self):
        expand = partial(default_safety_terms, lookup=lambda task: ["기계실", "끼임"])
        self.assertEqual(expand(BOOM_CHECK), ["붐", "점검", "기계실", "끼임"])

    def test_no_task_skips_lookup(self):
        calls = []
        expand = partial(default_safety_terms, lookup=lambda task: calls.append(task) or ["x"])
        self.assertEqual(expand(Intent(intent="procedure", parts=["붐"])), ["붐"])
        self.assertEqual(calls, [])  # 작업이 없으면 관계표를 찾지 않는다

    def test_safety_query_includes_lookup_terms(self):
        search = fake_search([])
        expand = partial(default_safety_terms, lookup=lambda task: ["작업반경"])
        search_safety("각도 확인", BOOM_CHECK, search, SAFETY, expand)
        self.assertEqual(search.calls[0][0], "각도 확인 붐 점검 작업반경")

    def test_with_real_taxonomy(self):
        expand = partial(default_safety_terms, lookup=TaxonomyService.from_directory().expand_query_terms)
        intent = Intent(intent="safety", parts=["메인 로프"], task="메인 로프 점검")
        self.assertEqual(expand(intent), ["메인 로프", "메인 로프 점검", "카 상부", "기계실", "추락", "끼임"])




class HelperTest(unittest.TestCase):
    def test_load_corpus_reads_all_pages(self):
        many = [{"id": f"c{i}", "text": "t", "metadata": {}} for i in range(7)]

        def get(doc_type, collection, limit=10, offset=0, where=None):
            return many[offset:offset + limit]

        self.assertEqual(len(load_corpus(get, "tech", "x", page_size=3)), 7)  # 3 + 3 + 1

    def test_distance_to_similarity_range(self):
        self.assertEqual(distance_to_similarity(0.0), 1.0)
        self.assertEqual(distance_to_similarity(2.0), 0.0)
        self.assertEqual(distance_to_similarity(3.0), 0.0)  # 범위를 넘어도 0~1로 자른다

def chunk(chunk_id, score=0.0):
    """merge_evidence 입력용 ScoredChunk."""
    return ScoredChunk(chunk_id=chunk_id, text="t", score=score, doc_type="tech")


class MergeEvidenceTest(unittest.TestCase):
    def test_keeps_search_order_instead_of_score(self):
        # BM25·태그로만 찾아 1등인 A(0.0)가 벡터 점수 높은 V보다 앞에 남는다
        evidence = merge_evidence([chunk("A"), chunk("V", 0.9)], [])
        self.assertEqual([c.chunk_id for c in evidence.chunks], ["A", "V"])

    def test_alternates_manual_and_safety(self):
        evidence = merge_evidence([chunk("m1"), chunk("m2"), chunk("m3")], [chunk("s1")])
        self.assertEqual([c.chunk_id for c in evidence.chunks], ["m1", "s1", "m2", "m3"])

    def test_keeps_first_of_duplicates_and_cuts_top_n(self):
        evidence = merge_evidence([chunk("x"), chunk("y")], [chunk("x"), chunk("z")], top_n=2)
        self.assertEqual([c.chunk_id for c in evidence.chunks], ["x", "y"])

    def test_bm25_only_answer_survives_with_real_search(self):
        corpus = [{"id": "A", "text": "HX-200A 메인 로프 교체 기준", "metadata": {"part": "메인 로프"}}]
        corpus += [{"id": f"V{i}", "text": f"일반 안내 {i}", "metadata": {}} for i in range(1, 10)]
        vector_only = fake_search([{**c, "distance": 0.9} for c in corpus if c["id"] != "A"])
        intent = Intent(intent="spec", parts=["메인 로프"])
        manual = search_manual("HX-200A 메인 로프 교체 기준", intent, vector_only, corpus)
        self.assertEqual(merge_evidence(manual, []).chunks[0].chunk_id, "A")


if __name__ == "__main__":
    unittest.main()