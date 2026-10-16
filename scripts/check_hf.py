"""Tạo/xác minh dataset private: python -m scripts.check_hf.

Đây là thao tác thật khi đủ cấu hình; không upload dữ liệu và không in token.
"""

from src.common.config import get_settings
from src.common.hf_io import ensure_repo


def main() -> int:
    """Kiểm tra cấu hình trước khi gọi mạng; trả mã lỗi rõ ràng."""
    try:
        settings = get_settings()
        settings.require_hf()
    except ValueError as error:
        print(f"Cấu hình chưa hợp lệ: {error}")
        return 2
    try:
        ensure_repo(settings)
    except Exception as error:
        # Không in body/header có thể chứa thông tin nhạy cảm của SDK.
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        print(f"Chưa xác minh được repo private: {type(error).__name__}"
              + (f" (HTTP {status})" if status is not None else ""))
        return 1
    print("Đã tạo hoặc xác minh dataset private. Chưa upload dữ liệu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
