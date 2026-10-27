from core.schemas import Evidence, ScoredChunk

EVIDENCE_TOP_N = 8


def merge_evidence(
    manual: list[ScoredChunk], safety: list[ScoredChunk], top_n: int = EVIDENCE_TOP_N
) -> Evidence:
    """매뉴얼·안전 문서 검색 결과를 합쳐 점수가 높은 순으로 상위 top_n개를 고른다.

    같은 chunk_id가 여러 번 나오면 점수가 가장 높은 것 하나만 남긴다.
    점수가 같으면 manual, safety 순서로 먼저 들어온 청크가 앞선다. 입력 리스트는 바꾸지 않는다.
    """
    best: dict[str, ScoredChunk] = {}
    for chunk in [*manual, *safety]:
        kept = best.get(chunk.chunk_id)
        if kept is None or chunk.score > kept.score:
            best[chunk.chunk_id] = chunk
    ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)
    return Evidence(chunks=ranked[:top_n])
