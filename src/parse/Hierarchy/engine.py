"""Gọi Parser C++ và chuyển kết quả sang các dataclass Python của M2."""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from .types import Element, Hierarchy

DEFAULT_MAPPING = Path(__file__).resolve().with_name("mapping.json")


@dataclass
class ParseResult:
    """Kết quả một Version; diagnostic.offset là vị trí byte UTF-8 trong đầu vào."""

    elements: list[Element]
    hierarchy: list[Hierarchy]
    diagnostics: list[dict[str, str | int]]
    ordered_children: dict[str, list[str]]

    @property
    def complete(self) -> bool:
        return not self.diagnostics


class HierarchyEngine:
    """Giữ một Parser C++ với metadata và mapping được nạp lúc khởi tạo.

    parse() nhận chuỗi LaTeX đã merge. Kiểm tra result.complete trước khi dùng
    các dòng cho bước sau; engine không tự bỏ qua diagnostic hay chuẩn hóa thêm.
    """

    def __init__(self, arxiv_id: str, version: int, mapping_path: str | Path = DEFAULT_MAPPING):
        try:
            self._native = import_module(f"{__package__}._hierarchy_native")
        except ImportError as error:
            raise ImportError(
                "Cannot load the C++ hierarchy extension. Build it with the current Python: "
                "python -m src.parse.Hierarchy.build"
            ) from error
        self._parser = self._native.HierarchyParser(arxiv_id, version, Path(mapping_path).resolve())

    def parse(self, latex: str) -> ParseResult:
        if not isinstance(latex, str):
            raise TypeError("latex must be a Python str")
        result = self._parser.parse(latex)
        return ParseResult(
            elements=[Element(row.element_id, row.arxiv_id, row.kind, row.content)
                      for row in result.elements],
            hierarchy=[Hierarchy(row.arxiv_id, row.version, row.element_id, row.parent_id)
                       for row in result.hierarchy],
            diagnostics=[{"code": item.code, "offset": item.offset,
                          "message": item.message, "source": item.source}
                         for item in result.diagnostics],
            ordered_children=result.ordered_children,
        )
