import json
import tempfile
import unittest
from pathlib import Path

from features.master.models import Taxonomy, TaskRelation
from features.master.taxonomy import TaxonomyService

TAXONOMY = {
    "부위": ["메인 로프"], "작업": ["메인 로프 점검", "메인 로프 점검 시험"],
    "작업 위치": ["카 상부", "기계실"], "위험 유형": ["추락", "끼임"],
}
RELATIONS = {
    "메인 로프 점검": {"작업 위치": ["카 상부", "기계실"], "위험 유형": ["추락", "끼임"]},
    "메인 로프 점검 시험": {"작업 위치": ["기계실"], "위험 유형": ["끼임"]},
}


def write(directory, name, content):
    """임시 폴더에 테스트용 파일을 쓰고 경로를 반환한다."""
    path = Path(directory) / name
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def make_service(synonyms=None):
    taxonomy = Taxonomy(["메인 로프"], ["메인 로프 점검", "메인 로프 점검 시험"],
                        ["카 상부", "기계실"], ["추락", "끼임"])
    relations = {
        "메인 로프 점검": TaskRelation("메인 로프 점검", ["카 상부", "기계실"], ["추락", "끼임"]),
        "메인 로프 점검 시험": TaskRelation("메인 로프 점검 시험", ["기계실"], ["끼임"]),
    }
    return TaxonomyService(taxonomy, relations, synonyms or {"와이어로프": "메인 로프", "카": "승강기 칸"})


class ShippedDataTest(unittest.TestCase):
    def test_data_files_load_and_agree_with_each_other(self):
        service = TaxonomyService.from_directory()
        self.assertEqual(list(service.taxonomy.by_axis()), ["부위", "작업", "작업 위치", "위험 유형"])
        self.assertEqual(len(service.relations), 5)
        self.assertEqual(service.normalize_term("와이어로프"), "메인 로프")
        self.assertEqual(service.expand_query_terms("메인 로프 점검"), ["카 상부", "기계실", "추락", "끼임"])


class NormalizeTest(unittest.TestCase):
    def test_whole_term_and_word_by_word(self):
        service = make_service({"브레이크 슈": "브레이크 라이닝", "와이어로프": "메인 로프"})
        self.assertEqual(service.normalize_term("와이어로프"), "메인 로프")
        self.assertEqual(service.normalize_term(" 브레이크 슈 "), "브레이크 라이닝")
        self.assertEqual(service.normalize_term("와이어로프 점검"), "메인 로프 점검")

    def test_only_whole_words_are_replaced(self):
        service = make_service()
        self.assertEqual(service.normalize_term("카드"), "카드")
        self.assertEqual(service.normalize_term("카 상부"), "승강기 칸 상부")
        self.assertEqual(service.normalize_term("없는 말"), "없는 말")


class ExpandTest(unittest.TestCase):
    def test_exact_task(self):
        self.assertEqual(make_service().expand_query_terms("메인 로프 점검"),
                         ["카 상부", "기계실", "추락", "끼임"])

    def test_task_inside_a_longer_phrase_uses_the_longest_match(self):
        service = make_service()
        self.assertEqual(service.expand_query_terms("메인 로프 점검 시험하는 법"), ["기계실", "끼임"])
        self.assertEqual(service.expand_query_terms("메인 로프 점검하는 법"),
                         ["카 상부", "기계실", "추락", "끼임"])

    def test_synonym_in_task_is_normalized_first(self):
        self.assertEqual(make_service().expand_query_terms("와이어로프 점검"),
                         ["카 상부", "기계실", "추락", "끼임"])

    def test_unknown_task_gives_empty_list(self):
        self.assertEqual(make_service().expand_query_terms("날씨"), [])
        self.assertEqual(make_service().expand_query_terms(""), [])

    def test_result_has_no_duplicates(self):
        taxonomy = Taxonomy([], ["작업"], ["기계실"], ["기계실"])
        relations = {"작업": TaskRelation("작업", ["기계실"], ["기계실"])}
        self.assertEqual(TaxonomyService(taxonomy, relations, {}).expand_query_terms("작업"), ["기계실"])


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_from_directory_reads_all_three_files(self):
        write(self.tmp.name, "taxonomy.json", TAXONOMY)
        write(self.tmp.name, "task_relations.json", RELATIONS)
        write(self.tmp.name, "synonyms.csv", "동의어,표준 태그\n와이어로프,메인 로프\n")
        service = TaxonomyService.from_directory(self.tmp.name)
        self.assertEqual(service.normalize_term("와이어로프"), "메인 로프")
        self.assertEqual(service.relations["메인 로프 점검 시험"].places, ["기계실"])

    def test_synonyms_accept_bom_and_blank_lines(self):
        path = write(self.tmp.name, "s.csv", "﻿동의어,표준 태그\n\n가버너,조속기\n\n")
        self.assertEqual(TaxonomyService.load_synonyms(path), {"가버너": "조속기"})

    def test_bad_synonym_files_raise(self):
        for content in ("동의어,표준 태그\n가,나\n가,다\n", "동의어,표준 태그\n하나만\n", "동의어,표준 태그\n,나\n"):
            with self.assertRaises(ValueError):
                TaxonomyService.load_synonyms(write(self.tmp.name, "s.csv", content))
        with self.assertRaises(ValueError):
            TaxonomyService.load_synonyms(Path(self.tmp.name) / "none.csv")

    def test_bad_taxonomy_files_raise(self):
        broken = {**TAXONOMY, "위험 유형": ["추락", 3]}
        missing = {k: v for k, v in TAXONOMY.items() if k != "작업"}
        for content in ("{not json", [], broken, missing):
            with self.assertRaises(ValueError):
                TaxonomyService.load_taxonomy(write(self.tmp.name, "t.json", content))

    def test_bad_relation_files_raise(self):
        for content in ([], {"작업": "문자열"}, {"작업": {"작업 위치": ["a"]}}):
            with self.assertRaises(ValueError):
                TaxonomyService.load_task_relations(write(self.tmp.name, "r.json", content))


class ValidationTest(unittest.TestCase):
    def test_relation_values_must_exist_in_taxonomy(self):
        taxonomy = Taxonomy(["부위"], ["작업"], ["기계실"], ["끼임"])
        wrong_place = TaskRelation("작업", ["없는 위치"], ["끼임"])
        wrong_hazard = TaskRelation("작업", ["기계실"], ["없는 위험"])
        for relation in (wrong_place, wrong_hazard):
            with self.assertRaises(ValueError):
                TaxonomyService(taxonomy, {"작업": relation}, {})
        with self.assertRaises(ValueError):
            TaxonomyService(taxonomy, {"모르는 작업": TaskRelation("모르는 작업")}, {})

    def test_synonym_standard_cannot_be_a_synonym(self):
        with self.assertRaisesRegex(ValueError, "also synonyms"):
            make_service({"가": "나", "나": "다"})


if __name__ == "__main__":
    unittest.main()
