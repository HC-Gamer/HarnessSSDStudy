# ⛔ 校验失败：段间 schema 校验验证

> 主题: 段间 schema 校验验证
> 质量评分: 0/100（门槛 60，旧公式会给 0）
> 评分轨迹: [] | 重写次数: 0
> 采集方式: none | LLM 调用: 0 次
> 走过的路径: analyze(sabotage:bad_key_points) → validate_analyze(FAIL) → abort

## 评分分项

| 分项 | 值 |
|------|-----|
| 平均字数 | 0 |
| 空洞用语命中 | 0 次  |
| 具体性信号 | 0 个 |
| 要点缺口 | 0 条 |
| 原始分 → 最终分 | 0 → 0 |

## 段间校验

| 段 | 结果 | 错误 | 警告 | 明细 |
|----|:----:|:---:|:---:|------|
| analyze | ❌ 拦截 | 3 | 2 | key_points[0] 类型错误: 期望 str，实际 dict；key_points[1] 类型错误: 期望 str，实际 int；key_points[2] 类型错误: 期望 str，实际 NoneType；summary 只有 3 |

## 数据来源

- （无）

## 摘要

摘要本身是好的，问题出在下面的要点数组里，模型把对象塞进了本该是字符串的位置。

## 关键要点

- {'text': '模型返回了 dict 而不是 str'}
- 42
- None

## 正文

> 本次运行在段间 schema 校验处终止，**没有产出文章**。
> 这是预期行为：坏数据下传会被下游当成合法输入去「补全」。

失败原因：

- [analyze] key_points[0] 类型错误: 期望 str，实际 dict
- [analyze] key_points[1] 类型错误: 期望 str，实际 int
- [analyze] key_points[2] 类型错误: 期望 str，实际 NoneType
