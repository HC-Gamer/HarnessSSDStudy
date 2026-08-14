"""``tests/eval_test.py`` 的发现别名（双保险）。

12-2 的官方文件名 ``eval_test.py`` 不匹配 pytest 默认的 ``test_*.py``，
虽然 ``pytest.ini`` 已经配了 ``python_files``，但 16-2 的自查清单里写的又是
``tests/test_eval.py``。这里一行 import 把两个名字都坐实，
任何一方的发现规则失效都不会漏跑评估用例。
"""

from tests.eval_test import *  # noqa: F401,F403
