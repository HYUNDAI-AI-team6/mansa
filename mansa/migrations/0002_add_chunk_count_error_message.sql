-- 처리가 끝났을 때 파이프라인이 기록하는 값을 담는 컬럼 두 개를 더한다. 한 번만 실행한다.
-- chunk_count: 저장한 청크 수(완료 때만 채운다).
-- error_message: 실패 사유(실패 때만 채운다). API 키와 스택 트레이스는 담지 않고 1,000자 안으로 줄여 넣는다.
ALTER TABLE `documents_info`
  ADD COLUMN `chunk_count` int NULL AFTER `status`,
  ADD COLUMN `error_message` varchar(1000) NULL AFTER `chunk_count`;
