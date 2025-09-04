import os
import time
import re
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.utils.http import RequestUtils
from app.core.config import settings
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
import xml.dom.minidom
from app.utils.dom import DomUtils
from urllib.parse import quote
from opencc import OpenCC


def retry(ExceptionToCheck: Any,
          tries: int = 3, delay: int = 3, backoff: int = 1, logger: Any = None, ret: Any = None):
    """
    :param ExceptionToCheck: 需要捕获的异常
    :param tries: 重试次数
    :param delay: 延迟时间
    :param backoff: 延迟倍数
    :param logger: 日志对象
    :param ret: 默认返回
    """

    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 0:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"未获取到文件信息，{mdelay}秒后重试 ..."
                    if logger:
                        logger.warn(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            if logger:
                logger.warn('请确保当前季度番剧文件夹存在或检查网络问题')
            return ret

        return f_retry

    return deco_retry


class ANiStrm(_PluginBase):
    # 插件名称
    plugin_name = "ANiStrm-DDSelfUsed"
    # 插件描述
    plugin_desc = "自动获取当季所有番剧，免去下载，轻松拥有一个番剧媒体库"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/CodeSmithDD/MoviePilot-Plugins/main/icons/anistrm.png"
    # 插件版本
    plugin_version = "2.4.4"
    # 插件作者
    plugin_author = "CodeSmithDD"
    # 作者主页
    author_url = "https://github.com/CodeSmithDD"
    # 插件配置项ID前缀
    plugin_config_prefix = "anistrm_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _onlyonce = False
    _fulladd = False
    _storageplace = None
    _custom_domain = None
    _convert_traditional = False
    _custom_season = None
    _get_custom_season = False  # 是否获取指定季度番剧（一次性操作）
    _opencc = OpenCC('t2s')

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._fulladd = config.get("fulladd")
            self._storageplace = config.get("storageplace")
            self._custom_domain = config.get("custom_domain") or "openani.an-i.workers.dev"
            self._convert_traditional = config.get("convert_traditional", False)
            self._custom_season = config.get("custom_season")
            self._get_custom_season = config.get("get_custom_season", False)
            # 加载模块
        if self._enabled or self._onlyonce:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._enabled and self._cron:
                try:
                    self._scheduler.add_job(func=self.__task,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="ANiStrm文件创建")
                    logger.info(f'ANi-Strm定时任务创建成功：{self._cron}')
                except Exception as err:
                    logger.error(f"定时任务配置错误：{str(err)}")

            if self._onlyonce:
                logger.info(f"ANi-Strm服务启动，立即运行一次")
                self._scheduler.add_job(func=self.__task, args=[self._fulladd], trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="ANiStrm文件创建")
                # 关闭一次性开关 全量转移
                self._onlyonce = False
                self._fulladd = False
            self.__update_config()

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def _clean_filename(filename):
        # 定义常见全角符号到半角符号的映射，或直接移除
        fullwidth_to_halfwidth = {
            '\uFF0D': '-',  # 全角破折号（－）替换为半角连字符（-）
            '\uFF1A': ':',  # 全角冒号（：）替换为半角冒号（:）
            '\uFF0C': ',',  # 全角逗号（，）替换为半角逗号（,）
            '\uFF0E': '.',  # 全角句号（。）替换为半角句号（.）
            '\uFF01': '!',  # 全角感叹号（！）替换为半角感叹号（!）
            '\uFF1F': '?',  # 全角问号（？）替换为半角问号（?）
            '\uFF08': '(',  # 全角左括号（（）替换为半角左括号（(）
            '\uFF09': ')',  # 全角右括号（））替换为半角右括号（)）
            '\uFF3B': '[',  # 全角左方括号（［）替换为半角左方括号（[）
            '\uFF3D': ']',  # 全角右方括号（］）替换为半角右方括号（]）
            '\u3000': ' ',  # 全角空格替换为半角空格
            # 其他全角符号可以直接移除（例如全角顿号、引号等）
            '\u3001': '',  # 全角顿号（、）
            '\u3002': '.',  # 全角句号（。）
            '\u201C': '"',  # 全角左双引号
            '\u201D': '"',  # 全角右双引号
            '\u2018': '\'',  # 全角左单引号
            '\u2019': '\'',  # 全角右单引号
        }

        # 替换全角符号
        for fullwidth, halfwidth in fullwidth_to_halfwidth.items():
            filename = filename.replace(fullwidth, halfwidth)

        # 去掉中文和中文之间的空格
        filename = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', filename)
        # 去掉中文和英文之间的空格
        filename = re.sub(r'([\u4e00-\u9fff])\s+([a-zA-Z0-9])', r'\1\2', filename)
        filename = re.sub(r'([a-zA-Z0-9])\s+([\u4e00-\u9fff])', r'\1\2', filename)
        # 将中文和中文之间的“-”替换为空格
        filename = re.sub(r'([\u4e00-\u9fff])\s*-([\u4e00-\u9fff])', r'\1 \2', filename)
        # 将中文和“-”替换为中文
        filename = re.sub(r'([\u4e00-\u9fff])(-)', r'\1', filename)

        return filename

    def _convert_title(self, title: str) -> str:
        title = self._clean_filename(title)
        if self._convert_traditional:
            return self._opencc.convert(title)
        return title

    def __validate_custom_season(self, season: str) -> bool:
        """验证自定义季度格式是否正确"""
        if not season:
            return False
        try:
            # 检查格式是否为"年份-月份"
            parts = season.split('-')
            if len(parts) != 2:
                return False

            year = int(parts[0])
            month = int(parts[1])
            # 验证月份是否为1、4、7、10中的一个（季度起始月）
            return month in [1, 4, 7, 10] and year > 2000
        except:
            logger.error(f"自定义季度格式错误: {season}，应为'年份-月份'，如'2025-1'")
            return False

    def __get_ani_season(self, idx_month: int = None) -> str:
        # 如果启用了获取指定季度且指定季度有效，则使用指定季度
        if self._get_custom_season and self._custom_season and self.__validate_custom_season(self._custom_season):
            self._date = self._custom_season
            logger.info(f"使用指定季度: {self._custom_season}")
            return self._custom_season

        current_date = datetime.now()
        current_year = current_date.year
        current_month = idx_month if idx_month else current_date.month
        for month in range(current_month, 0, -1):
            if month in [10, 7, 4, 1]:
                self._date = f'{current_year}-{month}'
                return f'{current_year}-{month}'

    @retry(Exception, tries=3, logger=logger, ret=[])
    def get_current_season_list(self) -> List:
        def _get_files(url: str) -> List:
            rep = RequestUtils(ua=settings.USER_AGENT if settings.USER_AGENT else None,
                               proxies=settings.PROXY if settings.PROXY else None).post(url=url, json={})
            logger.debug(rep.text)
            files_json = rep.json()['files']

            files = []
            for file in files_json:
                # 如果是文件夹，递归获取其中的文件
                if file.get('mimeType') == 'application/vnd.google-apps.folder':
                    folder_name = file['name']
                    # 对文件夹名进行编码以处理特殊字符
                    encoded_folder_name = quote(folder_name, safe='')
                    folder_url = f'{url}{encoded_folder_name}/'
                    logger.info(f'发现文件夹: {folder_name}, 递归获取其中文件: {folder_url}')
                    time.sleep(1)
                    files.extend(_get_files(folder_url))
                # 如果是视频文件，添加到结果列表
                elif file.get('mimeType') == 'video/mp4':
                    files.append(self._convert_title(file['name']))
            return files

        base_url = f'https://{self._custom_domain}/{self.__get_ani_season()}/'
        return _get_files(base_url)

    @retry(Exception, tries=3, logger=logger, ret=[])
    def get_latest_list(self) -> List:
        addr = 'https://api.ani.rip/ani-download.xml'
        ret = RequestUtils(ua=settings.USER_AGENT if settings.USER_AGENT else None,
                           proxies=settings.PROXY if settings.PROXY else None).get_res(addr)
        ret_xml = ret.text
        ret_array = []
        # 解析XML
        dom_tree = xml.dom.minidom.parseString(ret_xml)
        rootNode = dom_tree.documentElement
        items = rootNode.getElementsByTagName("item")
        for item in items:
            rss_info = {}
            # 标题
            title = DomUtils.tag_value(item, "title", default="")
            # 链接
            link = DomUtils.tag_value(item, "link", default="")
            rss_info['title'] = self._convert_title(title)
            rss_info['link'] = link.replace("resources.ani.rip", self._custom_domain)
            ret_array.append(rss_info)
        return ret_array

    def __touch_strm_file(self, file_name, file_url: str = None) -> bool:
        if not file_url:
            logger.debug(f'季度API生成的URL，使用新格式：{file_name}')
            # 季度API生成的URL，使用新格式
            encoded_filename = quote(file_name, safe='')
            #
            src_url = f'https://{self._custom_domain}/{self._date}/{encoded_filename}'
            logger.debug(f'季度API生成的SRL_URL: {src_url}')
        else:
            src_url = file_url

        # 检查API获取的URL格式是否符合要求
        if not self._is_url_format_valid(src_url):
            # 格式不符合要求，进行转换
            src_url = self._convert_url_format(src_url)

        logger.debug(f'创建 {file_name}.strm 文件，URL：{src_url}')
        file_path = f'{self._storageplace}/{file_name}.strm'
        if os.path.exists(file_path):
            logger.debug(f'{file_name}.strm 文件已存在')
            return False
        try:
            with open(file_path, 'w') as file:
                file.write(src_url)
                logger.debug(f'创建 {file_name}.strm 文件成功')
                return True
        except Exception as e:
            logger.error('创建strm源文件失败：' + str(e))
            return False

    def _is_url_format_valid(self, url: str) -> bool:
        """检查URL格式是否符合要求（.mp4?d=true）"""
        return url.endswith('.mp4?d=true')

    def _convert_url_format(self, url: str) -> str:
        """将URL转换为符合要求的格式"""
        if '?d=mp4' in url:
            # 将 ?d=mp4 替换为 .mp4?d=true
            return url.replace('?d=mp4', '.mp4?d=true')
        elif url.endswith('.mp4'):
            # 如果已经以.mp4结尾，添加?d=true
            return f'{url}?d=true'
        else:
            # 其他情况，添加.mp4?d=true
            return f'{url}.mp4?d=true'

    def __task(self, fulladd: bool = False):
        cnt = 0
        # 增量添加更新
        if not fulladd:
            rss_info_list = self.get_latest_list()
            logger.info(f'本次处理 {len(rss_info_list)} 个文件')
            for rss_info in rss_info_list:
                if self.__touch_strm_file(file_name=rss_info['title'], file_url=rss_info['link']):
                    cnt += 1
        # 全量添加当季
        else:
            name_list = self.get_current_season_list()
            logger.info(f'本次处理 {len(name_list)} 个文件')
            for file_name in name_list:
                if self.__touch_strm_file(file_name=file_name):
                    logger.debug(f'创建 {file_name}.strm 文件成功')
                    cnt += 1
        logger.info(f'新创建了 {cnt} 个strm文件')

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'fulladd',
                                            'label': '下次创建当前季度所有番剧strm',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 0 ? ? ?'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'storageplace',
                                            'label': 'Strm存储地址',
                                            'placeholder': '/downloads/strm'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'custom_domain',
                                            'label': '自定义域名',
                                            'placeholder': 'openani.an-i.workers.dev'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'get_custom_season',
                                            'label': '获取指定季度番剧(一次性)',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'custom_season',
                                            'label': '指定季度',
                                            'placeholder': '格式:年份-月份，如2025-1',
                                            'hint': '用于一次性获取指定季度番剧'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'convert_traditional',
                                            'label': '繁体转简体',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '自动从open ANi抓取下载直链生成strm文件，免去人工订阅下载' + '\n' +
                                                    '配合目录监控使用，strm文件创建在/downloads/strm' + '\n' +
                                                    '通过目录监控转移到link媒体库文件夹 如/downloads/link/strm  mp会完成刮削',
                                            'style': 'white-space: pre-line;'
                                        }
                                    },
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'emby容器需要设置代理，docker的环境变量必须要有http_proxy代理变量，大小写敏感，具体见readme.' + '\n' +
                                                    'https://github.com/honue/MoviePilot-Plugins',
                                            'style': 'white-space: pre-line;'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "fulladd": False,
            "storageplace": '/downloads/strm',
            "cron": "*/20 22,23,0,1 * * *",
            "custom_domain": "openani.an-i.workers.dev",
            "convert_traditional": False,
        }

    def __update_config(self):
        self.update_config({
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "enabled": self._enabled,
            "fulladd": self._fulladd,
            "storageplace": self._storageplace,
            "custom_domain": self._custom_domain,
            "convert_traditional": self._convert_traditional,
        })

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))


if __name__ == "__main__":
    anistrm = ANiStrm()
    name_list = anistrm.get_latest_list()
    print(name_list)
