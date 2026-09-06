# 功能总览

MDCx 支持的功能全景。只想快速上手的话，先看 [QUICKSTART.md](QUICKSTART.md)。

## 一、刮削系统

### 自动识别番号

从文件名提取番号（如 `ABP-123.mp4` → `ABP-123`），并自动判断类型：

| 类型 | 番号格式 | 例子 |
|------|---------|------|
| 有码 | 英文-数字 | ABP-123、SSIS-456 |
| 无码 | HEYZO-/Carib- 等 | HEYZO-123、Carib-123 |
| FC2 | FC2-PPV-数字 | FC2-PPV-1234567 |
| 国产 | MD-/MKY- 等 | MD-0123 |
| 欧美 | 数字.数字.数字.数字 | 123.45.67.89 |
| 素人 | SIRO- 等 | SIRO-1234 |

### 全部 35 个爬虫

| 爬虫名 | 数据源 | 说明 |
|--------|-------|------|
| dmm | dmm.co.jp | 日本最大成人平台 FANZA（仅能有码） |
| dmm_api | DMM 官方 Affiliate API | 直连 api.dmm.com/affiliate/v3（仅能有码） |
| thejavdb_api | api.thejavdb.net | TheJavDB API 数据源（免 CF，仅能有码） |
| javdb | javdb.com | JavDB 综合信息站（综合：有码+无码） |
| javdb_api | JavDB 镜像站 | 镜像站 HTML 直连，带简繁转换和异体字修正（综合：有码+无码） |
| javdb_app | JavDB 移动端 API | APK 逆向签名直连（综合：有码+无码；封面/海报/剧照走 App CDN 无水印原图，签名失效自动诊断，详见 docs/JAVDB_APP_SIGNATURE.md） |
| javbus | javbus.com | 有码/无码分类搜索（综合：有码+无码） |
| javlibrary | javlibrary.com | 老牌信息站（仅能有码） |
| missav | missav.ai | 综合搜索（综合：有码+无码） |
| missav_api | Recombee API | 免 CF 直连，演员字段留空（综合：有码+无码） |
| mgstage | mgstage.com | 有码/素人官网（仅能有码+素人） |
| prestige | prestige-av.com | Prestige 官网 JSON API（仅能有码+素人） |
| r18dev | r18.dev | JSON API 直连，番号自动补零（仅能有码） |
| official | 各官网 | 按番号前缀路由到子爬虫（综合：有码+无码） |
| avbase | av-base.net | 有码信息站（仅能有码+素人） |
| freejavbt | freejavbt.com | 磁力信息站（仅能有码） |
| mywife | mywife.cc | No. 素人番号（素人） |
| getchu | getchu.com | 游戏/视频综合（仅能有码，兼里番/动漫路由） |
| libredmm | libredmm.com | 开源信息站（仅能有码） |
| xcity | xcity.jp | 综合（仅能有码） |
| avsox | avsox.click | 无码（无码专属） |
| avmoo | avmoo.shop | 有码信息站（仅能有码） |
| aventertainments | aventertainments.com | 无码（DVD+PPV） |
| avheat | avheat.shop | 欧美（欧美） |
| airav_cc | airav.cc | 无码（综合：有码+无码） |
| avsex | avsex.com | 无码（综合：有码+无码） |
| fc2 | fc2.com | FC2 官网（FC2） |
| fc2ppvdb | fc2cmadb.com | FC2 PPV 数据库（FC2） |
| madouqu | madouqu.com | 国产（国产） |
| madou_club | madou.club | 麻豆社 国产（国产） |
| lulubar | lulubar.net | 仅能有码 |
| iqqtv | iqqtv.com | 综合：有码+无码+素人+国产 |
| javday | javday.tv | 综合：有码+无码+国产 |
| javfree | javfree.me | 综合：有码+FC2（素人） |
| 7mmtv | 7mmtv.sx | 综合：有码+无码+素人+FC2 |
| theporndb | api.theporndb.net | 欧美（欧美） |

> 注意：javdb_api、javdb_app、missav_api、r18dev、thejavdb_api 这五条是免 CF 直连通道，稳定性好，建议优先选用。

**各爬虫适用类型**（刮削类型默认网站源，可在「设置→站点」调整）：
- **仅能有码**：dmm、dmm_api、thejavdb_api、libredmm、r18dev、avbase、xcity、prestige、mgstage、getchu、javlibrary、freejavbt、lulubar、avmoo
- **无码专属**：aventertainments、avsox
- **综合（有码+无码）**：javbus、javdb、javdb_api、javdb_app、missav、missav_api、javday、javfree、airav_cc、avsex、official、iqqtv、7mmtv
- **素人**：mgstage、prestige、javbus、javdb 系、dmm、dmm_api、avbase、missav、missav_api、mywife、iqqtv、7mmtv
- **FC2**：fc2、fc2ppvdb、javdb 系、javfree、7mmtv
- **欧美**：theporndb、avheat
- **国产**：madouqu、madou_club、avsex、iqqtv、javday

### DMM 官方高清直链

- 封面/海报统一走 DMM 官方 awsimgsrc CDN 高清直链（竖版 `ps` 通常 1032×1469，部分系列为 745×1081 等中尺寸档；横版 `pl` 通常 2184×1469），由 `mdcx/crawlers/dmm_direct.py` 的番号→DMM cid 前缀映射生成，内置静态前缀表覆盖约 110 个主流系列（含 `h_xxx`/数字特殊前缀与跨厂商附加前缀），并叠加学习表自动扩充未收录系列的前缀。升级时校验分辨率宽≥700 过滤 147×200 缩略图占位图，避免把海报覆盖成低清缩略图。
- **LibreDMM / R18.dev / JavBus / JavDB / JavDB API / JavDB App / DMM / DMM API / JavLibrary / avbase** 十个爬虫在刮削时直接把返回的低清封面/海报升级为 DMM 高清（R18.dev 的 `jacket_full_url` 是 pics.dmm.co.jp 低清且部分系列 cid 未补零，JavBus 是自家 CDN 低清镜像，DMM/avbase 用域名替换 + dmm_direct 前缀表候选），无码番号自动跳过。
- **JavDB 系图源无水印升级**：JavDB / JavDB API / JavDB App 三站产出/落回的 javdb 图床图片，下载时自动改走 JavDB App 专用 CDN `tp.spfcas.com` 无水印原图（加密流下载层透明解密），替代带 javdb 水印的网页版 CDN；App CDN 路径中段由 javdb_app 响应自动学习，失效时自动回退网页版。DMM 升级链覆盖不到的番号（无码/FC2/老片等）落回 javdb 图源时受益。
- 开启「Poster 选优」（poster_auto_best）时，候选池自动注入 DMM 竖版高清候选，按尺寸自动胜过低清原图，其他爬虫也能受益。
- DMM 图下载失败按「设置→网络→重试」次数（默认 3 次）自动重试，应对 awsimgsrc 偶发的连接抖动。

### 多网站结果合并

多个爬虫返回的数据会按字段优先级合并。比如标题优先取 JavBus 的数据，简介优先取 DMM 的数据——每个字段都可以独立配置优先级。

字段优先级对话框中每个字段行还可勾选「跳过」：勾选后该字段不从任何来源抓取（保持 NFO 中的既有值），适合某些字段想全部手动维护、不被刮削结果覆盖的情况。按刮削类型（有码/无码等）可分别设置。

## 二、四种刮削模式

### 1. 正常模式（全新刮削）

从头到尾走一遍：扫描文件 → 刮数据 → 下图片 → 生成 NFO → 重命名 → 移动文件。

适合新下载的视频。

### 2. 整理模式（仅整理文件）

也叫视频模式。只刮番号用于命名，然后重命名和移动视频文件。**不下图片、不生成 NFO**。

适合不想弄海报墙、只想把文件按番号归类的人。

### 3. 更新模式

重新整理已有 NFO 的文件结构，按新的命名规则移动文件。

适合已经刮过、但想调整目录结构的情况。

### 4. 读取模式

四个独立选项自由组合：

| 选项 | 作用 |
|------|------|
| 有 NFO 时更新 | 按更新模式规则整理已有文件 |
| 无 NFO 时刮削 | 对没 NFO 的文件重新联网刮 |
| 重新下载 | 重新下载图片 |
| 更新 NFO | 更新 NFO 内容（如补演员 TMDB ID） |

## 三、NFO 文件生成

生成 Emby/Jellyfin/Kodi 通用的 .nfo 文件，包含 30+ 字段：

- **基本信息**：番号、标题、原始标题、简介、标语
- **发行信息**：发行日期、年份、分级、国家
- **人员**：演员（多语言名称）、导演、演员 TMDB ID
- **评分**：公众评分、影评人评分、想看数
- **分类**：标签、类型、系列
- **制作**：制作商、厂牌、发行商
- **媒体**：海报 URL、缩略图 URL、背景图 URL、预告片 URL
- **外部 ID**：各网站 ID（javdbid、javlibraryid 等）

写入时可通过 **NFO 合并策略**控制如何处理已存在的 NFO（软件界面读取模式区域下拉框，5 选 1）：偏好刮削结果 / 偏好本地 NFO / 数组字段合并 / 保留现有 / 仅填空缺，防止重刮覆盖手动整理的内容（如手改的简介、标签）。

## 四、图片处理

### 下载

自动下载海报、缩略图、背景图、额外剧照、预告片视频。

### 人脸裁剪

使用 OpenCV 人脸检测模型，自动检测海报中的人脸位置并裁剪为 2:3 标准比例的海报。

### 水印

支持在图片角落添加图标徽标水印（字幕/有码/无码/破解/流出/高清 4K·8K），可配置：
- 作用的图片类型（海报/缩略图/背景图分别开关）
- 水印大小（按图片高度比例档位）
- 添加规则（不固定自动轮转 / 固定到指定角落 / 按水印类型分别指定角落）

### Amazon 高清封面

从 Amazon 搜索高清封面图（1500px 尺寸），支持：
- EAN-13 条码识别 → ASIN 映射
- 三层搜索策略：条码快路径 → 标题搜索 → 演员名称兜底
- ASIN 数据库缓存（Excel 保存，避免重复搜索；写入按番号去重，同番号不重复入库；出厂库随版本更新，老用户启动时自动按番号合并新增/补全空缺，不覆盖用户已填值；合并产生新增行时按番号整体重排）

当前 Poster 已是 DMM 官方 awsimgsrc 高清图（宽≥700）时按分辨率直接放行、跳过日亚搜索——DMM 竖图普遍只有 170-420KB，原 400KB 字节阈值会误判为「不够清晰」而误走昂贵的日亚搜索；DMM 缩略图（147×200）与窄图仍会被拦截继续走日亚。

### 官方图源兜底（DMM / MGStage）

当所有图源站点均无法获取封面/海报时，按番号直构官方 CDN 高清图兜底（设置 → 下载「下载高清图」组可开关，默认开启）：
- **DMM**：直构 awsimgsrc 高清封面（横版），自动学习厂牌前缀：
  - 从刮削过程中观察到的真实 DMM URL（高清封面升级命中 + dmm 爬虫验证过的图）提取「系列 → 前缀」证据
  - 状态机管理：≥2 个不同番号验证成功转正（verified）、连续构造失败 ≥3 次隔离（quarantined）、新证据解除隔离重新验证
  - 学习数据持久化到 `userdata/dmm_prefix_learned.json`（原子写），仅记录验证成功的证据
  - CID 候选构造顺序：学习表 verified → 静态前缀表 → 学习表 provisional → 常见前缀盲试
- **MGStage**：站点图源全部失败时，直构 MGStage 官方 CDN 高清图——`pb_e` 横版大图（840 宽，高度随片源比例约 470~560）作封面兜底、`pf_e` 竖版小图（422×600）作海报兜底（系列映射表：LUXU/OTIM/CHUC/GERK/ONEZ/ONEX/MFC/ARA，来自 JavDB 高清图替换油猴脚本实测并经多番号实测验证），补上 DMM 不收录的素人番号场景
- 所有图片下载统一设 50MB 大小上限，防止异常大文件占用磁盘

## 五、翻译系统

6 个翻译引擎：

| 引擎 | 是否需要配置 | 说明 |
|------|-------------|------|
| Google | 不需要 | 免费，自动爬取接口 |
| Bing | 不需要 | 免费，国内网络友好 |
| 百度 | 需要 API Key | 需去百度翻译开放平台申请 |
| DeepL | 需要 API Key | 需去 DeepL 官网申请 |
| DeepLX | 需要自建 URL | 自建 DeepL 免费代理 |
| LLM | 需要 API Key/Base URL | 大模型翻译，可自定义 Prompt |

可以配置哪些字段需要翻译（标题、简介、标签等），以及多引擎降级策略（第一个不行就换下一个）。

## 六、演员数据库

以 Excel 文件（`userdata/actor_database.xlsx`）存储演员信息：

- **字段**：ID、日文名、中文名、繁体名、别名、信息链接、TMDB ID、出生日期、简介
- **自动补全**：通过 TMDB API 查询演员 ID 和多语言名称
- **数据来源**：TMDB、Wikidata、Gfriends、graphis.ne.jp
- **反向查询**：已知中文名找日文名，或反过来
 - **演员库维护工具**（软件工具页）：直接操作 `actor_database.xlsx`，独立按钮——补全中文名（按已有 TMDB ID 补中英繁体翻译）、补全 LibreDMM 链接（补信息链接）、补全别名（可选来源：TMDB、minnano 或 JavDB；默认仅补缺别名的条目，勾选「全量更新」并入全部行且不覆盖本地已有别名，配套「起始行/限量」分片续跑——中断后日志输出"将起始行填入 N-1 即可续跑"，处理日志带 [行N] 前缀便于人工定位）、JavDB 中文名（从 JavDB 移动端 API 查询演员中文名/繁体名，仅处理「中文名 == 日文原名」的行，用 name_zht 转简体补全，无需 TMDB API Key，支持分片续跑）、minnano 补全（从 minnano-av 补缺生日/简介，日文字段自动翻译）、检查用户库（扫描格式/结构/数据异常并弹窗报告，安全项可一键自动修复，tmdb 项给人工修复步骤）、剔除男演员（按 tmdbid 校验 TMDB gender 删除男优，删前备份到「男优备份」sheet，支持限量/可中断，gender 0/1/未知一律保留）、校验 tmdbid 有效性（清除 TMDB 失效 id 并按名字重搜补回）、更新 nfo tmdbid（用本地库新 id 覆盖 nfo 旧 id，持久源同步）、打开演员数据库（用系统默认程序打开 xlsx 供查看与手工编辑）。另设「停止当前维护任务」按钮独立于软件界面刮削停止，一键请求停止当前维护任务。网络请求采用滑动窗口并发（TMDB 并发 5 / LibreDMM 并发 2 / JavDB 并发 5），每个联网维护工具支持限量参数（默认 5000，配合幂等可多次运行逐片处理 2 万+ 行，断点续传），停止时保存已处理部分，日志实时显示在 GUI 日志页。无需输入演员名单或选择 nfo 目录
- **Emby 演员管理器**（左侧导航「演员管理」）：连接 Emby/Jellyfin 后获取演员列表（可配置只获取演员类型 / 重复去重），按可配置的数据源优先级匹配头像和背景图（Gfriends / graphis.ne.jp / minnano-av / 本地文件夹）与简介信息（本地演员库 / 维基百科 / minnano-av / 本地数据库），预览后批量同步到 Emby（仅补缺失或强制重新获取，同步完成后自动刷新列表）。Gfriends / Graphis / 信息链路已合并为统一函数，按数据源优先级依次尝试；本地文件夹头像匹配采用预扫描索引（`build_local_avatar_index`），将 N 次全树遍历降为 1 次；头像缓存持久化到 `userdata/emby_actor_cache/` 目录（不再随临时目录清理丢失）。「设置」可配置数据源优先级与获取过滤；「数据源测试」可输入演员名逐源验证；双击演员行打开详情编辑对话框，可编辑简介/信息并单独同步头像/简介；「清空缓存文件夹」清理已下载的头像缓存。底部状态栏实时显示连接与当前操作状态。

## 七、文件命名系统

使用 Jinja2 模板引擎自定义命名规则，支持条件渲染。

**支持的变量**：番号、标题、原标题、演员（当前名/第一名/全部）、番号字母前缀、简介、导演、系列、制作商、发行商、发行日期、发行年份、片长、有码/无码标识、清晰度、中文字幕标识、无码流出标识、原文件名、想看数、评分、4K 标识等（完整列表见设置 → 命名页内提示）。

**三种命名目标**：
1. 文件夹命名（如 `[ABP-123] 标题`）
2. 文件命名（如 `ABP-123.标题.mp4`）
3. NFO 标题（用于 Emby 展示）

## 八、Emby/Jellyfin 集成

- **Emby 演员管理器**（左侧导航「演员管理」）：独立顶层对话框（单例复用，重复点击导航还原已有窗口而不新开），连接 Emby 服务器获取演员列表，表格展示头像/简介/背景图/影片数状态，支持按媒体库筛选，支持仅补缺失或强制重新获取
- **多源头像匹配**：Gfriends 网络头像库 / graphis.ne.jp / minnano-av 爬虫 / 本地文件夹（预扫描索引加速），自动匹配头像和背景图并上传；三头像数据源已合并为统一函数链路，按优先级依次尝试
- **多源信息匹配**：本地演员库 `actor_database.xlsx`（最高优先，离线可用）→ Wikipedia 百科 → minnano-av 详细资料 → 本地 SQLite 数据库，支持出生日期、出生地、标签等字段
- **批量同步**：预览匹配结果后一键同步到 Emby 服务器
- **演员信息补全**：向 Emby 服务器同步演员简介、头像、元数据；优先使用本地 `actor_database.xlsx` 已入库的简介与出生日期（离线回填 Overview/PremiereDate，换行转 `<br/>`），本地命中且简介存在时跳过 wiki/minnano 网络来源，仅本地简介缺失才退回外部补齐
- **Kodi 演员 NFO**：生成 Kodi 兼容的演员头像文件

## 九、网络与反爬

- **HTTP 客户端**：curl-cffi 模拟浏览器 TLS 指纹，默认 7 种浏览器画像自动轮换（Chrome 124/131/136 Win + Chrome 136 Mac + Firefox 133/135 Win + Safari iOS；Amazon 刮削用专用桌面池 6 种）
- **网络连通性检测**：网络页「开始检测」按钮逐站检查连通性与刮削能力——镜像/动态域名站点多地址检测（主站+镜像），API 类爬虫走真实刮削探测，结果按基础环境/连通性/刮削站点/账号 API/辅助服务分组展示
 - **代理**：支持 HTTP/HTTPS/SOCKS5 代理；"走代理网站"列表支持域名与数据源名称两种写法——填数据源名（可从旁边下拉框直接选择，如 missav、javdb、7mmtv）时，该数据源的主域/镜像/备用域名均自动走代理，站点换域名无需改配置（议题 #83）；默认含 amazon.co.jp、m.media-amazon.com、xcity.jp、minnano-av.com、avbase.net、javbus.com、javdb.com、javlibrary.com、r18.dev、mgstage.com、prestige-av.com、seesaawiki.jp、avsox/avmoo/avheat 主镜像、无码官网五站、mywife.cc、github.com 系、google.com、missav 三镜像、aventertainments.com、javfree.me、7mmtv.sx、7tv022.com 等共 34 个域名，完整列表见设置 → 网络页），其他直连
- **Cloudflare 绕过**：通过外部 CF 服务（TRAWL `/scrape` 或 FlareSolverr `/v1`）自动绕过 CF 防护页，MDCx 自动拉起协议适配层翻译请求，无需内置浏览器；可选配置独立 Bypass 代理；Bypass 服务失效时自动跳过避免空等
- **Selenium CF Bypass（JavLibrary 专用）**：JavLibrary 遇 Cloudflare JS challenge 时自动 fallback 到 Selenium+Edge headless 获取页面 HTML（cf_selenium_bypass，默认开启）。需要 Windows 10/11 + Edge 浏览器，首次使用自动安装 selenium；无 Edge 环境优雅降级，连续失败 3 次进入 5 分钟冷却
- **Bypass 落地域名白名单**：可配置可信落地域名列表（逗号分隔，支持 `*.example.com` 子域通配），校验 Bypass 服务落地/重定向后的最终域名，防止第三方服务被劫持时把恶意页面当数据；留空表示不校验
- **限流**：并发数与全局线程延时控制请求节奏；Amazon 等高风控源使用自适应退避（429 自动降速冷却）
- **指纹伪装**：完整 sec-ch-ua、Accept-Language 等请求头，按请求类型动态调整

## 十、实用工具

- **NFO 库管理**：左侧导航独立页面，浏览和批量编辑整个 NFO 库——目录递归扫描生成列表（支持筛选）、列表顶部「全选/全不选」一键勾选、15 字段编辑表单、本地封面预览+裁剪、保存前字段级 diff 弹窗确认、批量替换演员名/加删标签/统一系列名、右键菜单（重新刮削/打开所在目录/删除 NFO）
- **字幕管理**：自动匹配、复制、重命名字幕文件
- **Emby 演员管理器**：连接 Emby 管理演员头像和简介，支持多数据源匹配和批量同步
- **缺失文件检测**：检查媒体库中缺失的文件
- **海报裁剪工具**：图形化裁剪海报，可拖拽选择区域
- **封面补图工具**：按番号批量补齐缺失的封面和缩略图，复用当前配置的站点优先级、命名、裁切、水印规则；所有爬虫站点都拿不到图时走 **DMM 官方高清直链兜底**（`dmm_direct`：番号→DMM cid 前缀映射生成 awsimgsrc 高清直链，内置约 110 个主流系列前缀表含 h_xxx 特殊前缀，并叠加学习表自动扩充未收录系列；竖版优先下 `ps` 高清作海报，竖版不存在/失败时下横版 `pl` 并复用 `cut_thumb_to_poster` 裁剪成海报；无码番号自动跳过）
- **演员库维护工具**：直接操作 `actor_database.xlsx`，一键补全中文名、LibreDMM 链接、别名（可选来源 TMDB/minnano/JavDB，默认仅补缺别名行，可全量并入，支持起始行/限量分片续跑）、JavDB 中文名（从 JavDB 移动端 API 查询演员中文名/繁体名，无需 TMDB API Key）、minnano 补全、检查用户库（扫描+自动修复安全项）、剔除男演员、校验 tmdbid 有效性、更新 nfo tmdbid、打开数据库查看编辑（复用当前配置的 TMDB API），并发请求日志实时显示
- **网络连通性检查**：一键测试各网站可不可达
- **相似片推荐**：结果树右键 →「查看相似片推荐」，基于 tag IDF 加权 Jaccard + 系列/片商/发行商/导演/评分/年份/时长/演员多维特征本地离线计算相似影片（借鉴 OpenAver 设计，零网络零模型），支持全部历史刮削结果（含跨会话），双击推荐项可跳转
- **命令行刮削**：`uv run crawl` 在终端中调试爬虫

## 十一、断点续刮与状态缓存

- **SQLite 刮削状态缓存**：刮削进度自动保存到 `userdata/scrape_state.db`（标准库 sqlite3 + WAL），程序重启或崩溃后再次刮削自动跳过已完成且未变化的文件（按 mtime 判断），从上次进度继续
- **读取模式不受缓存干扰**：读取模式（main_mode==4）始终处理全部选中文件，不跳过已完成的文件，不写入 done/failed 状态，确保维护操作覆盖完整
- **刮削缓存管理**：软件工具页刮削缓存面板可查看缓存统计（已完成/失败/总数）、刷新统计、导出缓存数据、重置缓存（清除已完成标记，下次全量重刮）、清空缓存（删除 scrape_state.db 文件）
- **失败跨会话重试**：失败文件自动记录，下次启动重新尝试，连续失败 3 次后停止自动重试（可在结果树中对失败项右键强制重刮）；成功即清零计数
- **结果摘要缓存**：刮削成功时存储相似推荐所需字段，供相似片推荐跨会话使用
- **安全回退**：数据库损坏或不可用时自动回退内存模式，行为与无缓存一致