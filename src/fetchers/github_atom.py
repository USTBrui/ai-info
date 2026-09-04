# -*- coding: utf-8 -*-
"""
GitHub 更新日志抓取器（releases.atom / commits.atom）

Author: wr

GitHub 的每个仓库都自带标准 Atom 订阅源，这是盯开源工具更新最省事的办法：
  版本发布：https://github.com/作者/仓库/releases.atom
  代码提交：https://github.com/作者/仓库/commits/分支名.atom

这个抓取器做的事情很简单：复用 RSS 解析，再给标题加上仓库名，
否则一堆「v1.2.3」摆在一起根本分不清是谁发的。
"""

from __future__ import annotations

import re

from .base import RawItem
from .rss import RSSFetcher

_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+)")


class GitHubAtomFetcher(RSSFetcher):
    """GitHub releases / commits 的 Atom 订阅"""

    type_name = "atom"

    def fetch(self) -> list[RawItem]:
        items = super().fetch()
        repo = self._repo_name(self.source.url)

        for item in items:
            if repo:
                item.extra["repo"] = repo
                # 原本标题多半只是 v1.2.3，加上仓库名才好认
                if not item.title.startswith(repo):
                    item.title = f"{repo} · {item.title}"
        return items

    @staticmethod
    def _repo_name(url: str) -> str:
        """从网址里抠出「作者/仓库名」"""
        match = _REPO_RE.search(url or "")
        if not match:
            return ""
        return f"{match.group(1)}/{match.group(2)}"
