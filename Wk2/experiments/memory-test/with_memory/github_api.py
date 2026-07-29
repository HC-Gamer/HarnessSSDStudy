"""
GitHub API 工具函数模块

提供从 GitHub API 获取仓库基本信息的函数。
所有 API 调用使用 requests 库，结果以结构化 JSON 返回。
"""

import logging
import time
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# GitHub API 基础地址
GITHUB_API_BASE = "https://api.github.com"

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# 请求重试次数
MAX_RETRIES = 3

# 重试间隔（秒）
RETRY_DELAY = 1


def get_repo_info(owner: str, repo: str) -> Optional[Dict[str, object]]:
    """获取指定 GitHub 仓库的基本信息。

    Args:
        owner: 仓库所有者（用户名或组织名）。
        repo: 仓库名称。

    Returns:
        包含仓库基本信息的字典，包含以下字段：
            - name: 仓库名称
            - full_name: 完整仓库名（owner/repo）
            - description: 仓库描述
            - stars: Star 数量
            - forks: Fork 数量
            - language: 主要编程语言
            - url: 仓库 URL

        如果请求失败或仓库不存在，返回 None。

    Raises:
        ValueError: 当 owner 或 repo 为空时抛出。
    """
    if not owner or not repo:
        raise ValueError("owner 和 repo 不能为空")

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("正在获取仓库信息: %s/%s (第 %d 次尝试)", owner, repo, attempt)
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            result = {
                "name": data.get("name"),
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "stars": data.get("stargazers_count"),
                "forks": data.get("forks_count"),
                "language": data.get("language"),
                "url": data.get("html_url"),
            }
            logger.info("成功获取仓库信息: %s/%s", owner, repo)
            return result

        except requests.exceptions.Timeout:
            logger.warning("请求超时: %s/%s (第 %d 次尝试)", owner, repo, attempt)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

        except requests.exceptions.RequestException as e:
            logger.error("请求失败: %s/%s - %s", owner, repo, str(e))
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    logger.error("获取仓库信息失败（已达最大重试次数）: %s/%s", owner, repo)
    return None
