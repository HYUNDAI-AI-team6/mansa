import math
import re
from collections import Counter

# shortcut: 띄어쓰기·기호로만 나눠 "브레이크를"과 "브레이크"를 다른 단어로 본다, 검색 품질이 부족하면 형태소 분석이나 글자 묶음(bigram)으로 바꾼다.

# 숫자 묶음과 글자 묶음을 따로 끊는다. "1000kg"이 표의 "Capacity (㎏): 1000"과 "1000"으로 맞도록 숫자와 단위를 나눈다
_WORD = re.compile(r"\d+|[^\W\d_]+")

def tokenize(text: str) -> list[str]:
    """글자·숫자 묶음 단위로 나누고 영문은 소문자로 바꾼다."""
    return _WORD.findall(text.lower()) 

def bm25_rank(
        question: str, chunks: list[tuple[str, str]], k1: float =1.5, b: float = 0.75
) -> list[tuple[str, float]]:
    """질문 단어가 들어간 청크를 BM25 점수가 높은 순으로 반환한다.
    
    chunks는 (청크 ID, 본문) 목록이다. 질문 단어가 하나도 없는 청크는 결과에서 뺀다.
    질문에 같은 단어가 여러 번 있어도 한 번만 샌다.
    반환 점수는 순서를 정하는 용도이며 범위가 정해져 있지 않아 ScoredChunk.score(0~1)에 그대로 넣지 않는다.
    """
    docs = [(chunk_id, tokenize(text)) for chunk_id, text in chunks] # 모든 청크를 미리 단어 목록으로 바꿔둔다.
    if not docs:
        return []
    avg_len = sum(len(tokens) for _, tokens in docs) / len(docs) # 청크 평균 단어 수. 이 청크가 평균보다 긴지 짧은지 비교할 때 쓴다.
    doc_freq = Counter(term for _, tokens in docs for term in set(tokens)) # 단어별로 몇 개 청크에 들어 있는지 세는 것.
                                                                           # set(tokens) 라서 한 청크 안에서 10번 나와도 1로 셈.
    query = set(tokenize(question)) #질문 단어. set이라서 중복이 없어진다.

    ranked = []
    for chunk_id, tokens in docs:
        term_freq = Counter(tokens) #이 청크 안에서 단어별로 몇 번 나왔는지 세는 것.
        score = 0.0
        for term in query:
            freq = term_freq[term]
            if freq == 0: #이 청크에 없는 단어는 건너 뛴다.
                continue
            idf = math.log(1 + (len(docs) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            # 흔한 단어일수록 작아지는 값이다.
            length_norm = 1 - b + b * len(tokens) / avg_len #긴 청크면 1보다 커져서 점수를 깎는다.
            score += idf * freq * (k1 + 1) / (freq + k1 * length_norm)
        if score > 0:
            ranked.append((chunk_id, score)) # 질문 단어가 하나도 없는 청크는 빼버린다.
    return sorted(ranked, key=lambda item: item[1], reverse=True)
