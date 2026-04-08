import os
from app.core.config import settings


def get_recent_chapters_text(book_id: str, current_chapter_num: int, n: int = 2) -> str:
    """
    抓取距离当前章最近的 n 章纯文本内容，为大模型提供情绪流和微观逻辑的强连贯性参考。

    :param book_id: 书名 ID (用于定位沙盒)
    :param current_chapter_num: 当前准备生成的章节号
    :param n: 往前追溯的章节数，默认前 2 章
    :return: 拼接好的前文完整内容字符串
    """
    if current_chapter_num <= 1:
        return "（这是本书第一章，暂无前文参考）"

    archive_dir = os.path.join(settings.DATA_DIR, book_id, "chapter_archive")
    text_blocks = []

    # 倒序往前推 n 章 (例如当前准备写第 4 章，n=2，则抓取第 2 章和第 3 章)
    start_idx = max(1, current_chapter_num - n)
    for i in range(start_idx, current_chapter_num):
        file_path = os.path.join(archive_dir, f"chapter_{i:03d}.md")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                # 读取时去掉顶部的 Markdown 标题（如 # 第 x 章），防止干扰
                content = f.read()
                text_blocks.append(f"【📖 第 {i} 章 完整原文】\n{content}")

    if not text_blocks:
        return "（暂未在本地读取到前文记录，请依赖大纲与碎片历史进行推演）"

    return "\n\n".join(text_blocks)