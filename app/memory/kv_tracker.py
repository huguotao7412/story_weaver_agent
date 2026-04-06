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
    # ⚖️ 全局战力铁律管理 (新增)
    # ==========================================

    def set_power_system_rules(self, rules: str):
        State = Query()
        self.system_table.upsert(
            {"key": "power_system_rules", "value": rules},
            State.key == "power_system_rules"
        )

    def get_power_system_rules(self) -> str:
        State = Query()
        record = self.system_table.search(State.key == "power_system_rules")
        return record[0]["value"] if record else "（暂无战力设定）"

    # ==========================================
    # 🕳️ 伏笔池：挖坑与填坑管理
    # ==========================================
    def add_unresolved_thread(self, thread_data: dict, chapter_num: int):
        """挖坑：记录结构化的悬念或死仇"""
        self.threads_table.insert({
            "content": thread_data["content"],
            "priority": thread_data.get("priority", "Medium"),
            "keywords": thread_data.get("keywords", []),
            "related_map": thread_data.get("related_map", "未知"),
            "created_in_chapter": chapter_num
        })

    def remove_resolved_thread(self, thread_id: int):
        """填坑：根据 ID 抹除已解决的伏笔"""
        try:
            self.threads_table.remove(doc_ids=[thread_id])
        except Exception as e:
            print(f"⚠️ [KVTracker] 尝试移除不存在的伏笔 ID {thread_id}: {e}")

    def get_active_threads_snapshot(self, current_map: str, query_keywords: str = "") -> str:
        """【过滤引擎】根据优先级和地图动态召回伏笔，防止上下文污染"""
        threads = self.threads_table.all()
        if not threads:
            return "（当前暂无未解悬念与未报之仇）"

        filtered_threads = []
        hidden_count = 0

        for t in threads:
            priority = t.get("priority", "Medium")
            related_map = t.get("related_map", "全局")

            # 过滤逻辑：
            # 1. High 级别绝对保留
            # 2. 地图匹配 或 属于'全局'的保留
            # 3. 极其粗略的关键词命中保留
            if priority == "High" or related_map in ["全局", current_map] or any(
                    k in query_keywords for k in t.get("keywords", [])):
                filtered_threads.append(t)
            else:
                hidden_count += 1

        # 排序：High 永远在最前面
        priority_map = {"High": 0, "Medium": 1, "Low": 2}
        filtered_threads.sort(key=lambda x: priority_map.get(x.get("priority", "Medium"), 1))

        # 截断：最多只喂给 LLM 5 个最相关的伏笔
        MAX_THREADS_TO_SHOW = 5
        final_threads = filtered_threads[:MAX_THREADS_TO_SHOW]

        snapshot = f"【🕳️ 动态召回未解伏笔池 (已隐藏 {hidden_count + max(0, len(filtered_threads) - MAX_THREADS_TO_SHOW)} 个非活跃跨地图小坑)】：\n"
        if not final_threads:
            return snapshot + "- 当前地图暂无待解决悬念\n"

        for t in final_threads:
            p_tag = "🔴主线死仇" if t.get('priority') == 'High' else (
                "🟡支线" if t.get('priority') == 'Medium' else "🟢日常")
            snapshot += f"- [ID: {t.doc_id}] {p_tag} (第{t['created_in_chapter']}章立下) {t['content']}\n"

        return snapshot