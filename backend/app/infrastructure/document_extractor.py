"""文档正文提取（P1-2，design §2.4.2）：PyMuPDF(PDF) / python-docx(Word) / 纯文本。"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DOCUMENT_MAX_TEXT_CHARS = 5000  # 与结构化输入上限一致（spec §5.2.1规则5 ≤5000字符）


class DocumentExtractError(Exception):
    """文档解析失败（保留原始文件，走任务失败重试路径）。"""


def extract_document_text(obs_key: str, filename: str, read_bytes) -> str:
    """按扩展名分发提取；read_bytes() 由调用方注入（本地回退 / OBS getObject）。"""
    ext = Path(filename or "").suffix.lower()
    data = read_bytes()
    try:
        if ext == ".pdf":
            return _extract_pdf(data)
        if ext == ".docx":
            return _extract_docx(data)
        if ext in (".txt", ".md"):
            return _truncate(data.decode("utf-8", errors="replace"))
        raise DocumentExtractError(f"不支持的文档类型: {ext}")
    except DocumentExtractError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentExtractError(f"文档解析失败: {exc}") from exc


def _extract_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    chunks: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            chunks.append(page.get_text())
    text = "\n".join(chunks).strip()
    if not text:
        raise DocumentExtractError("PDF 未提取到文本（可能为扫描件，扫描件请用图片导入）")
    return _truncate(text)


def _extract_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs).strip()
    if not text:
        raise DocumentExtractError("Word 文档未提取到正文")
    return _truncate(text)


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > DOCUMENT_MAX_TEXT_CHARS:
        logger.info("文档文本超长，截断至 %d 字符", DOCUMENT_MAX_TEXT_CHARS)
        return text[:DOCUMENT_MAX_TEXT_CHARS]
    return text
