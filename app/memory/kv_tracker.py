# 状态追踪器：基于 TinyDB 记录角色位置、法宝、好感度
# 状态追踪器：基于 TinyDB 记录角色位置、法宝、好感度等 Metadata
# app/memory/kv_tracker.py

import os
from tinydb import TinyDB, Query
from app.core.config import settings


class KVTracker:
    """
    轻量级键值对(KV)状态追踪器。
    用于脱离 LLM 上下文，长期记忆人物的等级、死活、地理位置与持有物品。
    """

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = settings.KV_DB_PATH

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = TinyDB(db_path)
        self.characters_table = self.db.table('characters')
        self.inventory_table = self.db.table('inventory')

    def update_character_state(self, name: str, key: str, value: str, chapter_num: int):
        """更新/插入角色状态 (如境界、死活、位置)"""
        Character = Query()
        char_record = self.characters_table.search(Character.name == name)

        if char_record:
            # 更新已存在角色
            self.characters_table.update(
                {key: value, f"last_updated_ch_{key}": chapter_num},
                Character.name == name
            )
        else:
            # 插入新角色记录
            self.characters_table.insert({
                "name": name,
                key: value,
                f"last_updated_ch_{key}": chapter_num
            })

    def update_inventory(self, owner: str, item_name: str, action: str, chapter_num: int):
        """更新物品归属 (如获得神器、消耗丹药)"""
        Inventory = Query()

        if action.upper() == "ADD":
            # 检查是否已存在该物品
            if not self.inventory_table.search((Inventory.owner == owner) & (Inventory.item_name == item_name)):
                self.inventory_table.insert({
                    "owner": owner,
                    "item_name": item_name,
                    "acquired_in_chapter": chapter_num
                })
        elif action.upper() == "REMOVE":
            # 从背包中移除
            self.inventory_table.remove((Inventory.owner == owner) & (Inventory.item_name == item_name))

    def get_world_bible_snapshot(self) -> str:
        """
        供下一次生成章节时调用，提取当前存活角色的最新状态快照
        注入到 state["world_bible_context"] 中
        """
        all_chars = self.characters_table.all()
        snapshot = "【当前人物 KV 状态快照】：\n"
        for char in all_chars:
            # 如果角色标明死亡，可以过滤掉或者单独列出
            status = char.get("status", "存活")
            location = char.get("location", "未知")
            level = char.get("level", "凡人")
            snapshot += f"- {char['name']}: {status} | 境界: {level} | 当前位置: {location}\n"

        return snapshot