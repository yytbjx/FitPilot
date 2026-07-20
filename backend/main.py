"""兼容入口：uv run python main.py …

实现位于 app.cli。
"""

from app.cli import main

if __name__ == "__main__":
    main()
