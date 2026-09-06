# MDCx-diy

![python](https://img.shields.io/badge/Python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-GPLv3-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Crawlers](https://img.shields.io/badge/Sites-36-brightgreen.svg)

<p align="center"><b>如果你觉得不错可否赏我杯奶茶费，谢谢！ 😊</b></p>

<table align="center">
  <tr>
    <td align="center"><img src="resources/Img/donate-wechat.jpg" width="180" alt="微信"><br><sub>微信</sub></td>
    <td width="40"></td>
    <td align="center"><img src="resources/Img/donate-alipay.jpg" width="180" alt="支付宝"><br><sub>支付宝</sub></td>
  </tr>
</table>

## MDCx-diy 是什么

MDCx-diy 是一个桌面工具，自动从 36 个网站抓取视频文件的元数据（标题、演员、封面、简介等），生成标准的 .nfo 文件和整理好的文件夹，给 Emby、Jellyfin、Kodi 这类媒体服务器直接用。

一句话：把一堆乱七八糟的视频文件，变成媒体服务器能认的整齐资料库。

## 快速安装

从 [GitHub Releases](https://github.com/cdlongbow/mdcx-diy/releases) 下载对应系统的压缩包，解压后双击运行。

详细安装说明：[docs/INSTALL.md](docs/INSTALL.md)

## 第一次使用

看这篇 5 分钟上手指南：[docs/QUICKSTART.md](docs/QUICKSTART.md)

## 文档导航

| 文档 | 适合谁看 | 内容 |
|------|---------|------|
| **[使用 Wiki](https://github.com/cdlongbow/mdcx-diy/wiki)** | **新用户先看这里** | 三分钟上手、常见问题 FAQ（90% 问题有答案） |
| [QUICKSTART.md](docs/QUICKSTART.md) | 所有人 | 5 分钟上手，完成第一次刮削 |
| [INSTALL.md](docs/INSTALL.md) | 需要安装的人 | 系统要求、Release/源码/Docker 三种安装方式 |
| [FEATURES.md](docs/FEATURES.md) | 想了解能做什么的人 | 全部功能、36 个网站列表、四种刮削模式 |
| [USER_GUIDE.md](docs/USER_GUIDE.md) | 日常使用的人 | 完整使用手册、常见问题、实际场景 |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | 想调设置的人 | 每个配置项是干什么的 |
| [changelog.md](docs/changelog.md) | 关注版本更新的人 | 每个版本改了啥 |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | 想改代码的人 | 项目架构、爬虫开发、测试、代码规范 |

## 核心特色

- **36 个网站爬虫** — 有码、无码、FC2、国产、欧美全覆盖，部分站点免 CF 直连
- **智能番号识别** — 自动判断番号类型（有码/无码/FC2/国产/欧美）
- **标准 NFO 生成** — 30+ 元数据字段，Emby/Jellyfin/Kodi 通用
- **多引擎翻译** — Google、Bing、Baidu、DeepL、DeepLX、LLM 共 6 种
- **图片处理** — 人脸裁剪、水印、Amazon 高清封面、官方图源兜底（DMM 高清封面自动学习厂牌前缀 + MGStage 素人高清海报）、JavDB 系图源无水印原图（App CDN 加密流自动解密）
- **演员数据库** — Excel 数据库 + TMDB/Wikidata/Gfriends 多源补全
- **Emby/Jellyfin 集成** — 自动同步演员信息和头像（Emby 演员管理器支持最大化/拖拽缩放，默认适配屏幕）
- **网络自检与标注** — 检测网络页结果着色 + 按状态复制诊断报告；设置页站点下拉框标注「日本IP限定/勿用日本节点」等区域规则，并回显最近一次自己网络的实测状态（✅可连通/⚠️需关注/❌连不通，悬停看检测时间与路由）；代理分流可选「全部走代理」交给 Clash 类软件裁决
- **异步并发** — 同时刮多个文件，不卡界面
- **Cloudflare 绕过** — 支持 TRAWL / FlareSolverr 外部 CF 服务自动绕过防护页；JavLibrary 专属 Selenium+Edge headless fallback；部分站点免 CF 通道（javdb_api、javdb_app、missav_api、r18dev、thejavdb_api）

## 开发者

```bash
git clone https://github.com/cdlongbow/mdcx-diy.git
cd mdcx-diy
uv sync --dev
uv run python main.py
```

推送前自检：
```bash
uv run check --skip-hook-install
```

## 交流群

[![Telegram](https://img.shields.io/badge/Telegram-Join_Chat-2CA5E0?style=flat&logo=telegram&logoColor=white)](https://t.me/+OVnB6Cw8gkxlYzM1)

## 上游项目

* [sqzw-x/mdcx](https://github.com/sqzw-x/mdcx) — Hazard804/mdcx项目前身，当前暂时停止维护
* [Hazard804/mdcx](https://github.com/Hazard804/mdcx) — 基于 sqzw-x/mdcx, 继续进行维护及优化
* [ZiPenOk/mdcx](https://github.com/ZiPenOk/mdcx) — 基于 Hazard804/mdcx, 进行优化改进

向相关开发者表示敬意！

## 授权许可

GPLv3。使用本项目代表你接受：
* 仅供学习和技术交流
* 使用本软件时请遵守当地法律法规
* 法律及使用后果由使用者自己承担
* 禁止用于商业用途
