# -*- coding: utf-8 -*-
"""兼容入口：python server.py 启动服务。"""
import sys

from app.run import main

if __name__ == "__main__":
    sys.exit(main())
