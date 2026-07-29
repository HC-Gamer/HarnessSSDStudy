# AI Knowledge Base V2 — Week 2 Pipeline Experiments

V2自动化知识库流水线。从Week 1的手动操作升级为全自动数据采集→分析→整理→保存。

## 项目结构
```
v2-pipeline/
├── hooks/
│   ├── validate_json.py    # JSON格式校验
│   └── check_quality.py    # 5维度质量评分
├── pipeline/
│   ├── model_client.py     # 统一LLM客户端（DeepSeek/Qwen/OpenAI）
│   ├── pipeline.py         # 四步流水线（采集→分析→整理→保存）
│   └── rss_sources.yaml    # RSS数据源配置
├── mcp_knowledge_server.py # MCP知识库Server
├── knowledge/
│   ├── articles/           # 最终文章（JSON）
│   └── raw/                # 原始采集数据
└── .github/workflows/
    └── daily-collect.yml   # 每日自动采集

## 技术栈
- Python 3.11+, httpx, pyyaml, python-dotenv
- LLM: DeepSeek Chat（默认远程生成调用）
- 无第三方AI SDK依赖，直接HTTP调用OpenAI兼容API

## 文件路径约定
所有脚本从项目根目录（v2-pipeline/）运行。导入路径：
- from pipeline.model_client import ... （项目根目录运行时）
- or sys.path.insert(0, str(Path(__file__).parent)) （从pipeline/目录内运行时）

## 数据格式
知识条目JSON格式：
```json
{
  "id": "github-20260727-001",
  "title": "...",
  "source_url": "https://...",
  "summary": "至少20字的摘要",
  "tags": ["agent", "llm"],
  "status": "review",
  "score": 7,
  "collected_at": "2026-07-27T..."
}
```
