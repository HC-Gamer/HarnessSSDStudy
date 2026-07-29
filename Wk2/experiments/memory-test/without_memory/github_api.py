# 获取 GitHub 仓库信息
# 注意：本文件在"无 Memory"模式下生成，没有 AGENTS.md 规范的约束

import requests
import json
import sys


def getGithubRepoInfo(owner, repoName):
    """Get repo info from GitHub API.
    
    Parameters:
    owner - repo owner (string)
    repoName - repo name (string)
    
    Returns: repo info dict
    """
    url = 'https://api.github.com/repos/' + owner + '/' + repoName
    
    print('Fetching repo info for: ' + owner + '/' + repoName)
    
    try:
        resp = requests.get(url)
        data = resp.json()
        
        info = {
            'name': data['name'],
            'fullName': data['full_name'],
            'desc': data['description'],
            'stars': data['stargazers_count'],
            'forks': data['forks_count'],
            'lang': data['language'],
            'url': data['html_url']
        }
        return info
    except Exception as e:
        print('Error: ' + str(e))
        return None


if __name__ == '__main__':
    if len(sys.argv) > 2:
        info = getGithubRepoInfo(sys.argv[1], sys.argv[2])
        if info:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print('Failed to get repo info')
    else:
        print('Usage: python github_api.py OWNER REPO')
