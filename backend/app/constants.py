"""领域常量：鲜/冻仓标记与备料写模型（禁替 / 允许冻顶鲜）。"""

STORAGE_FRESH = "fresh"
STORAGE_FROZEN = "frozen"
STORAGE_TYPES = (STORAGE_FRESH, STORAGE_FROZEN)

# 两套互斥写模型：
# forbidden       —— 禁替：鲜缺只跟鲜仓账，冻仓库存不参与鲜缺计算。
# allowed_frozen  —— 允许冻顶鲜：冻仓总量池可冲减鲜缺。
MODE_FORBIDDEN = "forbidden"
MODE_ALLOWED = "allowed_frozen"

# system_settings 单行 id
SETTING_ROW_ID = 1
