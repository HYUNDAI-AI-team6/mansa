# 관리자 평가 페이지 사용법

관리자 화면의 **평가(A4)** 기능 설명이다. 테스트셋 문항을 Q&A 응답기에 보내 답변을 받고,
그 답변을 채점해 지표·실패 사례·지연·토큰을 화면과 파일로 보여 준다.
코드는 `mansa/features/dashboard/evaluation/`에 있고, 화면은 `mansa/ui/evaluation.py`다.

> 현재 응답기와 채점 LLM은 **임시로 OpenAI Codex CLI**를 쓴다. 실제 Q&A 파이프라인(LLM·RAG)이 완성되면
> 응답기만 교체한다. 교체 방법은 [응답기 교체](#응답기-교체) 참고.

## 준비

1. Codex CLI를 설치하고 로그인한다. 터미널에서 `codex --version`이 동작해야 한다.
   (확인한 버전: `codex-cli 0.164.0`)
2. 패키지를 설치한다. 새로 추가한 Python 패키지는 없다.

```powershell
cd mansa
uv sync --locked
uv run python app.py
```

3. 관리자로 로그인 → 왼쪽 메뉴 **평가** → **평가 실행**.

- 평가 1회에 Codex를 **문항 수 × 2번**(답변 1번 + 채점 1번) 실행하고 Codex 사용량이 소모된다.
  임시 6문항 기준 약 3분 걸렸다.
- 평가는 앱 전체에서 동시에 하나만 실행된다. 실행 중이면 "이미 평가가 실행 중이에요"가 뜬다.

## 실행 흐름

```text
eval/testsets/tech_qa.json  ─ 테스트셋 읽기·검증 (testset.py)
        │
        ▼
응답기에 문항별 질문 (answerer.py → codex_cli.py)      진행률: 답변 받는 중 n/N
        │
        ▼
eval/save/<run_id>_answers.json  ─ 질문-답변 세트 저장 (storage.py)
        │
        ▼
채점: 규칙 채점 + LLM-as-judge (scoring.py, judge.py)  진행률: 채점하는 중 n/N
        │
        ▼
eval/save/<run_id>_result.json / _result.csv  ─ 결과 저장 → 화면 표시
```

- 테스트셋이 잘못되면 응답기를 부르기 전에 멈추고 화면에 이유를 보여 준다.
- 문항 하나가 실패(시간 초과 180초, Codex 오류)해도 나머지 문항은 계속 평가한다. 실패는 **LLM 오류**로 기록된다.
- 마지막 실행 시각은 **전체 평가가 끝난 시각**이다.
- 앱을 재시작하거나 메뉴로 다시 들어오면 `eval/save/`의 가장 최근 결과를 보여 준다.

## 파일 위치

모든 경로는 **저장소 루트** 기준이다(`mansa/` 안이 아니다).

| 경로 | 내용 | Git |
|---|---|---|
| `eval/testsets/tech_qa.json` | 테스트셋 | 올림 |
| `eval/save/<run_id>_answers.json` | 질문-답변 세트(답변·지연·토큰·오류) | 제외 |
| `eval/save/<run_id>_result.json` | 집계 결과. 화면이 읽는 파일 | 제외 |
| `eval/save/<run_id>_result.csv` | 결과표. 화면의 **결과표 내보내기 (CSV)** 로 받는 파일 | 제외 |

- `run_id`는 실행 시작 시각(`YYYYMMDD-HHMMSS`)이다. 실행마다 새 파일을 만들고 이전 결과를 덮어쓰지 않는다.
- CSV는 엑셀에서 한글이 깨지지 않도록 UTF-8 BOM으로 저장한다. 열은 `구분, 항목, 값`이다.
- Gradio는 실행 폴더 밖 파일을 내려받기로 내보내지 않으므로 `app.py`의 `launch(allowed_paths=[SAVE_DIR])`로
  `eval/save/`만 허용했다.

## 테스트셋 작성

```json
{
  "title": "기술 Q&A 테스트셋",
  "description": "정답 수치·정답 근거 포함",
  "cases": [
    {
      "id": "T01",
      "question": "[모델 A] 메인 로프 교체 기준이 뭐야?",
      "workflow": "L2",
      "expected_numbers": ["10%"],
      "expected_sources": ["manual-model-a:5.3.2"]
    }
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `id` | O | 문항 ID. 테스트셋 안에서 중복 불가 |
| `question` | O | 응답기에 보낼 질문 |
| `workflow` | O | `L2` 또는 `L3`. 실패 원인 분류에 쓴다 |
| `expected_numbers` | O | 답변에 그대로 나와야 하는 수치·단위 문자열 목록. 없으면 `[]` |
| `expected_sources` | O | 정답 근거 ID 목록. 응답기가 돌려주는 근거 ID와 형식이 같아야 한다. 없으면 `[]` |

- 필드가 빠졌거나, `workflow`가 다르거나, `id`가 중복되면 평가를 시작하지 않는다.
- 지금 들어 있는 6문항과 정답 값은 **임시값**이다. 실제 문서가 확정되면 바꾼다.
- L2·L3의 정식 정의는 아직 없다. 지금은 L2를 문서 검색 경로, L3를 기준정보(모델 사양) 조회 경로로 가정했다.

## 지표 계산

| 지표 | 문항 통과 조건 | 비고 |
|---|---|---|
| 검색 적중률 | 정답 근거 중 하나 이상이 검색 결과에 있음 | 높을수록 좋음 |
| 수치 정확도 | `expected_numbers`가 모두 답변에 있음 | 높을수록 좋음 |
| 출처 정확도 | 정답 근거가 모두 답변의 인용 근거에 있음 | 높을수록 좋음 |
| 과잉 첨부율 | 인용 근거 중 정답이 아닌 근거의 비율(문항 평균) | **낮을수록 좋음** |
| 표현 일관성 | 채점 LLM이 용어·단위 표기가 일관된다고 판정 | 높을수록 좋음 |

- 목표값은 정해지지 않아 **임시로 60% 이상**이고, 과잉 첨부율만 40% 이하다. `ui/evaluation.py`의 `TARGET_PERCENT`, `LOWER_IS_BETTER`.
- 계산에 필요한 정보를 응답기가 하나도 주지 않은 지표는 0%가 아니라 **"값 없음"** 으로 표시한다.
  지금 Codex 응답기는 문서 검색을 하지 않으므로 검색 적중률·출처 정확도·과잉 첨부율이 항상 "값 없음"이다.
- LLM 오류 문항은 계산 가능한 지표에서 실패로 센다([LLM 오류](#llm-오류) 참고).
- 수치 비교는 **부호·숫자·단위(대소문자 포함)가 모두 같아야** 맞은 것으로 본다. 공백·전각 문자·천 단위 쉼표·
  유니코드 빼기 기호는 정규화한 뒤 비교한다. 대소문자는 바꾸지 않는다(`MPa`와 `mPa`는 다른 단위).
  - 맞지 않음: `1000 kg` ↔ `-1000 kg`, `11000 kg`, `1/1000 kg`, `1000 KG` / `5 mm` ↔ `1e5 mm` /
    `0.5 mm` ↔ `0.5 mm²`, `0.5 mm/s` / `10` ↔ `10 mm`, `10%` / `1 MPa` ↔ `1 mPa`
  - 맞음: `0.5 mm` ↔ `0.5mm 이하`, `0.5 ㎜` / `105 m/min` ↔ `105 m / min` / `1000 kg` ↔ `1,000 kg`, `500kg,1000kg`
  - 천 단위가 아닌 쉼표는 목록 구분자로 본다. 그래서 소수점 쉼표(`0,5 mm`)는 지원하지 않는다.
  - 복합 단위: `10 N`은 `10 N·m`, `10 N*m`, `10 N×m`, `10 N-m`, `10 N.m` 안에서, `0.5 mm`는 `0.5 mm^2` 안에서 맞지 않는다.
    `*`·`×`·`-`·`.`은 뒤에 단위 글자가 올 때만 막으므로 `10 mm × 20 mm`(치수), `10N-20N`(범위), 문장 끝 `0.5mm.`은 맞는다.
  - 단위 환산(`1000 mm` = `1 m`)은 하지 않는다. 한글 단위(절·초·회)는 뒤에 붙는 조사와 구분할 수 없어 뒤 경계를 검사하지 않는다.

### 실패 원인

하나라도 통과하지 못한 지표가 있는 문항이 실패 사례에 나온다.

| 원인 | 조건 |
|---|---|
| 검색 | 검색 결과에 정답 근거가 하나도 없음 |
| 조회 | 검색 실패가 아닌 `L3` 문항 |
| 생성 | 검색 실패가 아닌 `L2` 문항 |

"기대 → 실제"는 처음 실패한 항목 하나만 설명한다. 예: `0.5 mm → 0.7 mm`.
LLM 오류는 실패 사례가 아니라 아래 LLM 오류 목록에 나온다.

### LLM 오류

답변 LLM(응답기)이나 채점 LLM(judge) 호출이 실패한 경우다. 시간 초과, 오류 종료, 채점 결과 JSON 해석 실패가 해당한다.

| 단계 | 지표 처리 |
|---|---|
| 답변 | 수치 정확도·표현 일관성에서 실패로 센다. 전 문항이 오류면 두 지표는 0%다. 검색 적중률·출처 정확도는 응답기가 근거 정보를 주는 경우에만 실패로 센다 |
| 채점 | 표현 일관성에서 실패로 센다 |

- 화면에서는 실패 사례 카드 아래 **LLM 오류 n건** 카드(질문, 단계, 사유)로 따로 보여 준다. 오류가 없으면 카드가 나오지 않는다.
- 결과 JSON의 `llm_errors`, CSV의 `LLM 오류` 행에도 남는다.
- 채점 오류와 다른 품질 실패(예: 수치 틀림)가 함께 있으면 실패 사례와 LLM 오류 양쪽에 나온다.

### 지연·토큰

- 기술 Q&A 평균 지연·토큰은 측정값이 있는 문항만 평균한다.
- 고객센터는 평가 대상이 아니라 지연·토큰 항목도 없다.
- Codex 응답기의 지연에는 CLI 기동 시간이, 토큰에는 Codex 자체 시스템 프롬프트(질문 1개에 약 2만)가 포함된다.
  **실제 파이프라인 수치와 비교하지 않는다.**

## 재채점

채점 규칙이나 judge를 바꾼 뒤 답변을 다시 받지 않고 저장된 질문-답변 세트로 채점만 다시 할 수 있다.
결과는 새 `run_id`로 저장된다. judge는 여전히 Codex를 호출한다.

```powershell
cd mansa
uv run python -c "from pathlib import Path; from features.dashboard.evaluation.runner import rescore; from features.dashboard.evaluation.judge import CodexJudge; print(list(rescore(Path('../eval/save/<run_id>_answers.json'), CodexJudge()))[-1].metrics)"
```

## 응답기 교체

응답기는 아래 형태만 맞추면 된다(`features/dashboard/evaluation/answerer.py`의 `Answerer`).

```python
class Answerer(Protocol):
    name: str
    def answer(self, case: TestCase) -> AnswerRecord: ...
```

`AnswerRecord` 필드:

| 필드 | 설명 |
|---|---|
| `case_id` | 문항 ID |
| `answer_text` | 답변 본문 |
| `cited_ids` | 답변이 인용한 근거 ID 목록. 제공하지 않으면 `None` |
| `retrieved_ids` | 검색된 근거 ID 목록. 제공하지 않으면 `None` |
| `latency_sec` | 응답 시간(초) |
| `tokens` | 사용 토큰 수 |
| `error` | 호출 실패 메시지. 실패해도 예외 대신 이 값을 채워 돌려준다 |

- `None`은 "제공하지 않음"이고 `[]`는 "제공했지만 0개"다. 이 차이로 "값 없음"과 0%가 갈린다.
- 실제 파이프라인(`origin/feat/32-schemas`의 `QAService`)을 붙일 때는 `Answer`의 영역별 `source_ids`를 `cited_ids`로,
  `Evidence`의 `chunk_id`를 `retrieved_ids`로 옮기는 어댑터를 만든다. 지연은 어댑터에서 호출 전후로 잰다.
- 교체 후 `ui/evaluation.py`의 `_run()`에서 `CodexAnswerer()`를 새 응답기로 바꾼다. 채점 LLM도 정식 모델이
  정해지면 `CodexJudge()`를 바꾼다.

## 테스트

```powershell
cd mansa
uv run --locked python -B -m unittest discover -s tests -v
```

평가 관련 테스트는 `tests/test_eval_*.py`이며 Codex를 실제로 호출하지 않는다(가짜 응답기·judge·실제 출력 픽스처
`tests/fixtures/codex_exec.jsonl` 사용).

## 현재 한계

- 임시 응답기라 문서 근거 없이 답하므로 수치 정확도가 낮게 나온다(임시 6문항 실행 시 0%).
- 답변 LLM과 채점 LLM이 같은 Codex라 자기 답을 후하게 볼 수 있다.
- 평가 이력 비교, 테스트셋 편집 화면, 병렬 실행은 없다.
- Codex 모델은 Codex 기본 설정을 따른다. `CodexAnswerer(model=...)`, `CodexJudge(model=...)`로 바꿀 수 있다.
