-- 문서 목록 테이블. 현재 DB에 있는 documents_info의 정의 그대로다(SHOW CREATE TABLE 기준).
-- 이미 있으면 아무것도 하지 않는다. departments 테이블이 먼저 있어야 한다.
CREATE TABLE IF NOT EXISTS `documents_info` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `filename` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `document_type` enum('tech','secure') NOT NULL,
  `department_id` bigint DEFAULT NULL,
  `status` enum('PROCESSING','COMPLETED','FAILED') NOT NULL DEFAULT 'PROCESSING',
  `upload_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_documents_filename_type` (`filename`,`document_type`),
  KEY `idx_documents_status_upload` (`status`,`upload_at`),
  KEY `fk_documents_department` (`department_id`),
  CONSTRAINT `fk_documents_department` FOREIGN KEY (`department_id`) REFERENCES `departments` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
