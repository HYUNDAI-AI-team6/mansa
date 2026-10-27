"""평가 실행 흐름: 테스트셋 → 답변 수집 → 질문-답변 세트 저장 → 채점 → 결과 저장."""

from collections.abc import Callable, Generator, Iterator
from datetime import datetime
from pathlib import Path

from features.dashboard.evaluation import scoring, storage
from features.dashboard.evaluation.answerer import Answerer
from features.dashboard.evaluation.judge import Judge
from features.dashboard.evaluation.models import (
    AnswerRecord,
    EvalProgress,
    EvalReport,
    TestSet,
)
from features.dashboard.evaluation.testset import load_testset

Clock = Callable[[], datetime]


def run_evaluation(
    answerer: Answerer,
    judge: Judge,
    testset_path: Path = storage.TESTSET_PATH,
    save_dir: Path = storage.SAVE_DIR,
    clock: Clock = datetime.now,
) -> Iterator[EvalProgress | EvalReport]:
    """테스트셋 전체를 평가한다. 진행 중에는 EvalProgress를, 마지막에 EvalReport를 한 번 yield한다.

    테스트셋이 잘못되면 응답기를 부르기 전에 TestSetError가 난다. 문항 하나의 응답 실패는
    오류 기록으로 남기고 계속한다. save_dir에 answers·result JSON·CSV를 새로 만든다(덮어쓰지 않음).
    """
    testset = load_testset(testset_path)
    total = len(testset.cases)
    run_id = storage.new_run_id(save_dir, clock())
    started_at = _iso(clock())
    records: list[AnswerRecord] = []
    yield EvalProgress(0, total)
    for case in testset.cases:
        # 여기서 LLM이 답함
        records.append(answerer.answer(case))
        yield EvalProgress(len(records), total)
    answers_path = storage.save_answers(
        run_id, testset.title, answerer.name, started_at, records, save_dir
    )
    report = yield from _score(testset, records, judge, run_id, answerer.name, clock)
    report.answers_file = answers_path.name
    storage.save_report(report, save_dir)
    yield report


def rescore(
    answers_path: Path,
    judge: Judge,
    testset_path: Path = storage.TESTSET_PATH,
    save_dir: Path = storage.SAVE_DIR,
    clock: Clock = datetime.now,
) -> Iterator[EvalProgress | EvalReport]:
    """저장된 질문-답변 세트만으로 다시 채점한다. 응답기는 부르지 않는다.

    결과는 새 실행 ID로 저장해 이전 결과를 덮어쓰지 않는다. 세트에 없는 문항은 오류 문항으로 센다.
    """
    testset = load_testset(testset_path)
    meta, loaded = storage.load_answers(answers_path)
    by_id = {r.case_id: r for r in loaded}
    records = [
        by_id.get(c.id, AnswerRecord(c.id, error="no answer recorded"))
        for c in testset.cases
    ]
    run_id = storage.new_run_id(save_dir, clock())
    answerer_name = str(meta.get("answerer", "unknown"))
    report = yield from _score(testset, records, judge, run_id, answerer_name, clock)
    report.answers_file = answers_path.name
    storage.save_report(report, save_dir)
    yield report


def _score(
    testset: TestSet,
    records: list[AnswerRecord],
    judge: Judge,
    run_id: str,
    answerer_name: str,
    clock: Clock,
) -> Generator[EvalProgress, None, EvalReport]:
    """문항별로 judge·규칙 채점을 하고 집계한 EvalReport를 return한다.

    judge 진행률은 stage="judge"인 EvalProgress로 yield한다. 오류 문항은 judge를 부르지 않는다.
    """
    total = len(testset.cases)
    scores, failures, llm_errors = [], [], []
    for done, (case, record) in enumerate(zip(testset.cases, records), start=1):
        # 채점 LLM이 돌아가는 곳
        judgement = None if record.error else judge.judge(case, record)
        # 코드로 채점하는곳
        score = scoring.score_case(case, record, judgement)
        scores.append(score)
        failure = scoring.classify_failure(case, record, score, judgement)
        if failure is not None:
            failures.append(failure)
        llm_errors.extend(scoring.collect_llm_errors(case, record, judgement))
        yield EvalProgress(done, total, stage="judge")
    return EvalReport(
        run_id=run_id,
        testset_title=testset.title,
        answerer=answerer_name,
        total=total,
        finished_at=_iso(clock()),
        metrics=scoring.compute_metrics(scores),
        failures=failures,
        latency=scoring.compute_latency(records),
        llm_errors=llm_errors,
    )


def _iso(moment: datetime) -> str:
    """초 단위 ISO 8601 문자열."""
    return moment.isoformat(timespec="seconds")
