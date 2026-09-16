"""统一日志：控制台(INFO) + 文件(DEBUG 滚动)。

框架里所有请求、断言、fixture 的清理动作都通过这里输出，
定位失败时先看 logs/autotest.log 和 Allure 报告里的请求/响应附件。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from config.setting import LOG_FILE

_FMT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LOGGERS = {}


def get_logger(name: str = "shopxo") -> logging.Logger:
    """按名称获取 logger（同名只初始化一次，避免重复输出）。"""
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        logger.addHandler(console)

        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        logger.addHandler(file_handler)

    _LOGGERS[name] = logger
    return logger
