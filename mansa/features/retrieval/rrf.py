def rrf_merge(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """여러 검색 결과 순위를 RRF(Reciprocal Rank Fusion)로 합친다.
    
    rankings는 검색 방식별 청크 ID 목록이며 앞에 있을수록 순위가 높다.
    청크마다 1/ (k + 순위)를 모든 목록에서 더해 점수가 높은 순으로 반환된다.
    한 목록에 같은 ID가 여러 번 있으면 가장 높은 순위만 샌다.
    반환 점수는 순서를 정하는 용도이며 ScoredChunk.score(0~1)에 그대로 넣지 않는다.
    """
    scores: dict[str, float] = {} # 청크별 점수를 모아둘 빈 딕셔너리
    for ranking in rankings:
        seen: set[str] = set() # 이번 목록에서 이미 세어본 ID를 기억해 둘 곳. 목록마다 새로 비운다.
        for rank, chunk_id in enumerate(ranking, start=1): 
            if chunk_id in seen: # 이번 목록에서 이미 세어본 ID면 건너뛴다.
                continue
            seen.add(chunk_id) # 지금 ID를 "셌음"으로 표시해
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    # (ID, 점수) 쌍을 점수(item[1]) 기준으로 큰 것부터 정렬해서 돌려주기
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
