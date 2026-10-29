"""업로드한 원본 PDF 파일을 {저장소}/{doc_type}/{문서 id}.pdf 로 두고 지운다.

사용자가 정한 파일 이름은 경로에 쓰지 않는다(문서 ID와 문서 유형만으로 경로를 만든다). 그래서 이름에 들어 있는
"../" 같은 값으로 저장소 밖에 쓰는 일이 없다. 저장은 같은 폴더의 임시 파일에 먼저 하고 이름을 바꿔서 끝내므로,
저장하다 멈춰도 반쯤 쓴 파일이 {id}.pdf 로 남지 않는다.
"""

import os
import shutil
import uuid
from pathlib import Path

import config
from features.documents.errors import DocumentStorageError
from features.documents.models import DOC_TYPES

TEMP_SUFFIX = ".tmp"


def _check_type(doc_type: str) -> None:
    """알려진 문서 유형이 아니면 ValueError를 발생시킨다."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type: {doc_type!r}, expected one of {list(DOC_TYPES)}")


def _check_id(document_id: int) -> None:
    """문서 ID가 1 이상의 정수가 아니면 ValueError를 발생시킨다."""
    if isinstance(document_id, bool) or not isinstance(document_id, int) or document_id < 1:
        raise ValueError(f"document_id must be an int >= 1, got {document_id!r}")


class PdfStorage:
    """원본 PDF 파일 저장소. 기준 폴더를 지정하지 않으면 config.PDF_STORAGE_DIR를 쓴다."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """기준 폴더를 받는다. 폴더는 처음 저장할 때 만든다."""
        self.base_dir = Path(base_dir) if base_dir is not None else Path(config.PDF_STORAGE_DIR)

    def path_for(self, document_id: int, doc_type: str) -> Path:
        """문서의 원본 PDF 경로를 계산한다. 파일이 있는지는 확인하지 않는다."""
        _check_id(document_id)
        _check_type(doc_type)
        return self.base_dir / doc_type / f"{document_id}.pdf"

    def save_temp(self, source_path: str | Path, doc_type: str) -> Path:
        """업로드된 파일을 저장소의 임시 파일로 복사하고 그 경로를 돌려준다. 원본 파일은 건드리지 않는다.

        복사하지 못하면(원본이 없거나 쓸 수 없음) DocumentStorageError를 발생시키고 임시 파일은 남기지 않는다.
        """
        _check_type(doc_type)
        folder = self.base_dir / doc_type
        temp = folder / f".upload-{uuid.uuid4().hex}{TEMP_SUFFIX}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, temp)
        except OSError as exc:
            self.discard(temp)
            raise DocumentStorageError("could not save the uploaded file") from exc
        return temp

    def commit(self, temp: Path, document_id: int, doc_type: str) -> Path:
        """임시 파일의 이름을 {문서 id}.pdf 로 바꿔 저장을 마친다. 같은 이름의 파일이 있으면 덮어쓴다.

        이름을 바꾸지 못하면 DocumentStorageError를 발생시킨다(임시 파일은 그대로 두므로 호출하는 쪽이 discard로 지운다).
        """
        target = self.path_for(document_id, doc_type)
        try:
            os.replace(temp, target)
        except OSError as exc:
            raise DocumentStorageError("could not store the uploaded file") from exc
        return target

    def discard(self, temp: Path) -> None:
        """임시 파일을 지운다. 이미 없거나 지우지 못해도 오류를 내지 않는다(정리 단계라서 원래 오류를 가리지 않는다)."""
        try:
            Path(temp).unlink(missing_ok=True)
        except OSError:
            pass

    def delete(self, document_id: int) -> bool:
        """문서의 원본 PDF를 지운다. 지웠으면 True, 이미 없으면 False다. 다시 불러도 안전하다.

        문서 유형을 몰라도 지울 수 있도록 모든 유형 폴더에서 찾는다(문서 ID는 유형과 상관없이 하나뿐이다).
        파일이 있는데 지우지 못하면 DocumentStorageError를 발생시킨다.
        """
        _check_id(document_id)
        removed = False
        for doc_type in DOC_TYPES:
            path = self.path_for(document_id, doc_type)
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DocumentStorageError("could not delete the stored file") from exc
        return removed
