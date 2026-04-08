# app/memory/kv_tracker.py

import os
import json
import aiosqlite
from app.core.config import settings


class AsyncKVTracker:
    """
    基于 aiosqlite 的纯异步键值对(KV)状态追踪器。
    【彻底解决 TinyDB 造成的事件循环阻塞问题】
    """

    def __init__(self, book_id: str = "default_book"):
        self.db_path = os.path.join(settings.DATA_DIR, book_id, "kv_state.sqlite")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    async def init_db(self):
        """异步初始化数据库表结构（每次实例化后必须 await 此方法）"""
        async with aiosqlite.connect(self.db_path) as db:
            # system_state 表：存放全局环境、规则等
            await db.execute('''CREATE TABLE IF NOT EXISTS system_state (key TEXT PRIMARY KEY, value TEXT)''')
            # characters 表：存放角色信息，灵活字段存入 JSON
            await db.execute('''CREATE TABLE IF NOT EXISTS characters (name TEXT PRIMARY KEY, data TEXT)''')
            # inventory 表：物品流转
            await db.execute('''CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, item_name TEXT, acquired_in_chapter INTEGER)''')
            # threads 表：伏笔池
            await db.execute('''CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, priority TEXT, keywords TEXT, related_map TEXT, created_in_chapter INTEGER)''')
            await db.commit()

    # ==========================================
    # 🗺️ 全局地图与核心标签管理
    # ==========================================
    async def set_global_map(self, map_name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)',
                             ("current_map", map_name))
            await db.commit()

    async def get_global_map(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT value FROM system_state WHERE key = ?', ("current_map",)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "新手村"

    async def set_core_character(self, name: str, is_core: bool = True):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT data FROM characters WHERE name = ?', (name,)) as cursor:
                row = await cursor.fetchone()
                char_data = json.loads(row[0]) if row else {"name": name, "location": "未知"}
            char_data["is_core"] = is_core
            await db.execute('INSERT OR REPLACE INTO characters (name, data) VALUES (?, ?)',
                             (name, json.dumps(char_data, ensure_ascii=False)))
            await db.commit()

    # ==========================================
    # 👤 角色与物品基础状态更新
    # ==========================================
    async def update_character_state(self, name: str, key: str, value: str, chapter_num: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT data FROM characters WHERE name = ?', (name,)) as cursor:
                row = await cursor.fetchone()
                char_data = json.loads(row[0]) if row else {"name": name, "is_core": False}

            char_data[key] = value
            char_data[f"last_updated_ch_{key}"] = chapter_num
            await db.execute('INSERT OR REPLACE INTO characters (name, data) VALUES (?, ?)',
                             (name, json.dumps(char_data, ensure_ascii=False)))
            await db.commit()

    async def update_inventory(self, owner: str, item_name: str, action: str, chapter_num: int):
        async with aiosqlite.connect(self.db_path) as db:
            if action.upper() == "ADD":
                # 检查是否已存在
                async with db.execute('SELECT id FROM inventory WHERE owner = ? AND item_name = ?',
                                      (owner, item_name)) as cursor:
                    if not await cursor.fetchone():
                        await db.execute(
                            'INSERT INTO inventory (owner, item_name, acquired_in_chapter) VALUES (?, ?, ?)',
                            (owner, item_name, chapter_num))
            elif action.upper() == "REMOVE":
                await db.execute('DELETE FROM inventory WHERE owner = ? AND item_name = ?', (owner, item_name))
            await db.commit()

    # ==========================================
    # 📸 快照生成 (🌟 冷热数据分离)
    # ==========================================
    async def get_world_bible_snapshot(self) -> str:
        current_map = await self.get_global_map()
        active_chars = []
        dead_chars = []
        frozen_count = 0
        dead_count = 0

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT data FROM characters') as cursor:
                async for row in cursor:
                    char = json.loads(row[0])
                    status = char.get("status", "存活")

                    if any(keyword in status for keyword in ["死", "亡", "陨落", "灭", "已故"]):
                        dead_count += 1
                        dead_chars.append(f"- {char['name']} (状态: {status})") # 🌟 将死者登记造册
                        continue

                    if char.get("is_core", False) or char.get("location", "未知") == current_map:
                        active_chars.append(char)
                    else:
                        frozen_count += 1

            snapshot = f"【🗺️ 当前主地图】：{current_map}\n"
            snapshot += f"【🌟 活跃人物状态快照 (已冻结 {frozen_count} 个跨地图冷数据，清理 {dead_count} 个已故角色)】：\n"

            if not active_chars:
                snapshot += "- 暂无活跃角色记录\n"
            for char in active_chars:
                core_tag = "[🔥核心主角团]" if char.get("is_core") else "[📍本地配角]"
                snapshot += f"- {char['name']} {core_tag}: {char.get('status', '存活')} | 境界: {char.get('level', '凡人')} | 位置: {char.get('location', '未知')}\n"

            async with db.execute('SELECT owner, item_name, acquired_in_chapter FROM inventory') as cursor:
                items = await cursor.fetchall()
                if items:
                    snapshot += "\n【🎒 核心角色物品与功法清单】：\n"
                    for item in items:
                        snapshot += f"- {item[0]} 拥有/已学会: {item[1]} (登记于第{item[2]}章)\n"
                else:
                    snapshot += "\n【🎒 核心角色物品】：当前背包空空如也\n"

        if dead_chars:
            snapshot += "\n【☠️ 死亡/陨落名单 (绝对禁止复活，除非世界观允许)】：\n"
            snapshot += ", ".join(dead_chars) + "\n"

        return snapshot

    # ==========================================
    # 全局战力与伏笔管理
    # ==========================================
    async def set_power_system_rules(self, rules: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)',
                             ("power_system_rules", rules))
            await db.commit()

    async def get_power_system_rules(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT value FROM system_state WHERE key = ?', ("power_system_rules",)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "（暂无战力设定）"

    async def add_unresolved_thread(self, thread_data: dict, chapter_num: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO threads (content, priority, keywords, related_map, created_in_chapter) VALUES (?, ?, ?, ?, ?)',
                (thread_data["content"], thread_data.get("priority", "Medium"),
                 json.dumps(thread_data.get("keywords", []), ensure_ascii=False),
                 thread_data.get("related_map", "未知"), chapter_num))
            await db.commit()

    async def remove_resolved_thread(self, thread_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM threads WHERE id = ?', (thread_id,))
            await db.commit()

    async def get_active_threads_snapshot(self, current_map: str, query_keywords: str = "") -> str:
        filtered_threads = []
        hidden_count = 0

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    'SELECT id, content, priority, keywords, related_map, created_in_chapter FROM threads') as cursor:
                async for row in cursor:
                    t = {"id": row[0], "content": row[1], "priority": row[2], "keywords": json.loads(row[3]),
                         "related_map": row[4], "created_in_chapter": row[5]}
                    if t["priority"] == "High" or t["related_map"] in ["全局", current_map] or any(
                            k in query_keywords for k in t["keywords"]):
                        filtered_threads.append(t)
                    else:
                        hidden_count += 1

        priority_map = {"High": 0, "Medium": 1, "Low": 2}
        filtered_threads.sort(key=lambda x: priority_map.get(x["priority"], 1))
        MAX_THREADS_TO_SHOW = 5
        final_threads = filtered_threads[:MAX_THREADS_TO_SHOW]

        snapshot = f"【🕳️ 动态召回未解伏笔池 (已隐藏 {hidden_count + max(0, len(filtered_threads) - MAX_THREADS_TO_SHOW)} 个非活跃跨地图小坑)】：\n"
        if not final_threads: return snapshot + "- 当前地图暂无待解决悬念\n"

        for t in final_threads:
            p_tag = "🔴主线死仇" if t['priority'] == 'High' else ("🟡支线" if t['priority'] == 'Medium' else "🟢日常")
            snapshot += f"- [ID: {t['id']}] {p_tag} (第{t['created_in_chapter']}章立下) {t['content']}\n"
        return snapshot