# app/memory/kv_tracker.py

import os
from tinydb import TinyDB, Query
from app.core.config import settings


class KVTracker:
    """
    轻量级键值对(KV)状态追踪器。
    【百万字升级版】：支持冷热数据分离与地图冻结机制。
    """

    def __init__(self, book_id: str = "default_book"):
        db_path = os.path.join(settings.DATA_DIR, book_id, "kv_state.json")

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = TinyDB(db_path)

        # 数据表定义
        self.characters_table = self.db.table('characters')
        self.inventory_table = self.db.table('inventory')
        self.system_table = self.db.table('system_state')  # 🌟 新增：存放全局状态（如当前所在地图）
        self.threads_table = self.db.table('unresolved_threads')

    # ==========================================
    # 🗺️ 全局地图与核心标签管理
    # ==========================================
    def set_global_map(self, map_name: str):
        """更新主角当前所在的全局主地图 (换地图)"""
        State = Query()
        self.system_table.upsert(
            {"key": "current_map", "value": map_name},
            State.key == "current_map"
        )

    def get_global_map(self) -> str:
        """获取当前的全局主地图"""
        State = Query()
        record = self.system_table.search(State.key == "current_map")
        return record[0]["value"] if record else "新手村"

    def set_core_character(self, name: str, is_core: bool = True):
        """将角色标记为核心（主角团），无视地图冻结，永久作为热数据保留"""
        Character = Query()
        if self.characters_table.search(Character.name == name):
            self.characters_table.update({"is_core": is_core}, Character.name == name)
        else:
            self.characters_table.insert({"name": name, "is_core": is_core, "location": "未知"})

    # ==========================================
    # 👤 角色与物品基础状态更新
    # ==========================================
    def update_character_state(self, name: str, key: str, value: str, chapter_num: int):
        """更新/插入角色状态 (如境界、死活、位置)"""
        Character = Query()
        char_record = self.characters_table.search(Character.name == name)

        if char_record:
            # 更新已存在角色（不会覆盖 is_core 等其他已有字段）
            self.characters_table.update(
                {key: value, f"last_updated_ch_{key}": chapter_num},
                Character.name == name
            )
        else:
            # 插入新角色记录 (🌟 默认非核心角色)
            self.characters_table.insert({
                "name": name,
                key: value,
                "is_core": False,
                f"last_updated_ch_{key}": chapter_num
            })

    def update_inventory(self, owner: str, item_name: str, action: str, chapter_num: int):
        """更新物品归属 (如获得神器、消耗丹药)"""
        Inventory = Query()

        if action.upper() == "ADD":
            if not self.inventory_table.search((Inventory.owner == owner) & (Inventory.item_name == item_name)):
                self.inventory_table.insert({
                    "owner": owner,
                    "item_name": item_name,
                    "acquired_in_chapter": chapter_num
                })
        elif action.upper() == "REMOVE":
            self.inventory_table.remove((Inventory.owner == owner) & (Inventory.item_name == item_name))

    # ==========================================
    # 📸 快照生成 (🌟 冷热数据分离引擎 + 死亡清理)
    # ==========================================
    def get_world_bible_snapshot(self) -> str:
            """
            供 Planner 和 Writer 调用。
            执行冷热过滤与生死过滤：只返回 【存活核心角色】 + 【当前地图存活配角】。
            """
            current_map = self.get_global_map()
            all_chars = self.characters_table.all()

            active_chars = []
            frozen_count = 0
            dead_count = 0  # 💡 新增：记录已被清理的死者数量

            for char in all_chars:
                is_core = char.get("is_core", False)
                location = char.get("location", "未知")
                status = char.get("status", "存活")

                # 💡 核心修复：死亡判定。如果状态包含死/亡/陨落，直接跳过，不占用宝贵的上下文
                if any(keyword in status for keyword in ["死", "亡", "陨落", "灭", "已故"]):
                    dead_count += 1
                    continue

                # 🌟 核心过滤逻辑：你是核心主角团，或者你就在当前地图，才会被唤醒
                if is_core or location == current_map:
                    active_chars.append(char)
                else:
                    frozen_count += 1

            snapshot = f"【🗺️ 当前主地图】：{current_map}\n"
            # 💡 更新提示语，让大模型知道系统做了自动清理
            snapshot += f"【🌟 活跃人物状态快照 (已冻结 {frozen_count} 个跨地图冷数据，清理 {dead_count} 个已故角色)】：\n"

            if not active_chars:
                snapshot += "- 暂无活跃角色记录\n"

            for char in active_chars:
                status = char.get("status", "存活")
                location = char.get("location", "未知")
                level = char.get("level", "凡人")
                # 打上直观的 Tag 方便大模型理解角色重要度
                core_tag = "[🔥核心主角团]" if char.get("is_core") else "[📍本地配角]"

                snapshot += f"- {char['name']} {core_tag}: {status} | 境界: {level} | 位置: {location}\n"

            return snapshot

    # ==========================================
    # 🕳️ 伏笔池：挖坑与填坑管理
    # ==========================================
    def add_unresolved_thread(self, content: str, chapter_num: int):
        """挖坑：记录新的悬念或死仇"""
        self.threads_table.insert({
            "content": content,
            "created_in_chapter": chapter_num
        })

    def remove_resolved_thread(self, thread_id: int):
        """填坑：根据 ID 抹除已解决的伏笔"""
        try:
            self.threads_table.remove(doc_ids=[thread_id])
        except Exception as e:
            print(f"⚠️ [KVTracker] 尝试移除不存在的伏笔 ID {thread_id}: {e}")

    def get_active_threads_snapshot(self) -> str:
        """获取当前所有未解伏笔，附带唯一 ID，供大模型阅读"""
        threads = self.threads_table.all()
        if not threads:
            return "（当前暂无未解悬念与未报之仇）"

        snapshot = "【🕳️ 当前未解伏笔/悬念/仇恨池】：\n"
        for t in threads:
            # TinyDB 会自动为每条记录生成 doc_id
            snapshot += f"- [ID: {t.doc_id}] (第{t['created_in_chapter']}章立下) {t['content']}\n"
        return snapshot