# ShopXO 电商平台 API 自动化测试

<!-- 仓库：https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test -->
[![API 自动化测试](https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test/actions/workflows/api-test.yml/badge.svg)](https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test/actions/workflows/api-test.yml)

基于 **Pytest + Requests** 的电商平台接口自动化测试项目，采用**分层设计 + 数据驱动 + 环境自适应 + 双轨分层**：
**284 条用例**（98 条真实环境接口回归 + 186 条框架离线自测）覆盖用户、商品、搜索、购物车、订单、地址、优惠券、商家后台等模块，
包含正向 / 边界 / 异常用例与「登录 → 搜索 → 加购 → 下单 → 取消」完整 E2E 闭环，
接入 Allure / HTML 报告、自包含质量看板与 **GitHub Actions + Jenkins** 流水线，支持 PR 门禁与定时回归。

- 被测系统：ShopXO 开源电商系统（前台 App API `index.php?s=/api/*`，商家后台 `admin.php?s=/admin/*`）
- 当前测试环境：`http://shop-xo.hctestedu.com`（华测教育公开沙箱）
- 最近一次全量回归：**265 passed / 12 skipped / 7 xfailed / 0 failed**（284 条用例，耗时约 30s；
  其中 186 条框架离线自测 **1.3s** 跑完、0 网络依赖）
- 质量看板：`reports/dashboard.html`（自包含单文件，可离线打开）；**每次执行按运行编号归档，历史结果不会被覆盖**
- 仓库地址：[github.com/jialinj505-crypto/ShopXO-API-Automation-Test](https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test)
  （获取代码：`git clone https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test.git`）

---

## 一、技术栈

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| 语言 | Python 3.10+ | 类型注解 + 面向对象封装 |
| 测试框架 | Pytest | 参数化、fixture、marker、插件生态 |
| 请求库 | Requests | Session 连接复用 + 统一请求驱动 |
| 报告 | Allure + pytest-html | Allure 呈现用例层级/步骤/请求响应附件，HTML 便于快速分享 |
| 结构校验 | jsonschema | 响应字段/类型的契约校验 |
| 并行/重试 | pytest-xdist / pytest-rerunfailures | 大批量回归加速、不稳定用例重跑 |
| 单测/Mock | responses + pytest-cov | **框架自身的离线单测**（mock HTTP，0 网络依赖）+ `core/` 覆盖率门禁 |
| CI | GitHub Actions + Jenkins | PR 门禁跑离线自测（秒级、不受别人沙箱影响）；定时任务跑真实环境回归并归档质量看板 |

---

## 二、分层架构

```
tests/            用例层：只写业务场景与断言（数据驱动，不含请求细节）
   └── conftest.py   fixtures：环境初始化/销毁、鉴权、数据清理、能力门控
api_objects/      接口层：一个类=一个业务模块，一个方法=一个接口（路由/参数/幂等性声明）
core/             框架层：请求驱动、统一鉴权、断言、数据加载、环境探测、Allure 适配
config/           配置层：环境地址、超时重试策略、账号、目录、默认业务数据
data/             数据层：JSON 测试数据集 + schemas 响应结构定义
tools/            工具层：测试数据维护与预检脚本
run.py            统一执行入口（本地与 CI 共用）
Jenkinsfile       CI 流水线定义
```

**分层收益**：接口变更时只改 `api_objects/*`，用例与断言不受影响；
测试数据变更时只改 `data/*.json`，不用动代码；环境切换只改环境变量。

### 目录结构

```
MyTestProject/
├── api_objects/                     # 接口层（Page Object 思想）
│   ├── admin_api.py                 #   商家后台（会话鉴权）
│   ├── address_api.py               #   收货地址 + 地区
│   ├── cart_api.py                  #   购物车
│   ├── coupon_api.py                #   优惠券（插件能力）
│   ├── goods_api.py                 #   商品详情/规格/收藏
│   ├── home_api.py                  #   首页聚合数据
│   ├── order_api.py                 #   订单全流程
│   ├── search_api.py                #   商品搜索
│   └── user_api.py                  #   登录/消息/积分/留言
├── core/                            # 框架层
│   ├── allure_utils.py              #   Allure 适配（未安装时自动降级为空操作）
│   ├── assert_helper.py             #   统一断言（业务码/msg/schema/金额/分页）
│   ├── auth.py                      #   统一 Token 鉴权封装（缓存/失效重登）
│   ├── base_api.py                  #   请求驱动（重试/超时/日志/附件/curl）
│   ├── dashboard.py                 #   质量看板渲染（自包含 HTML，内联 SVG 图表）
│   ├── data_loader.py               #   数据驱动加载器（含 ${USER}/${PWD} 占位符）
│   ├── env_check.py                 #   环境能力探测（决定哪些模块可执行）
│   ├── logger.py                    #   统一日志（控制台 + 滚动文件）
│   └── report_plugin.py             #   结果归档插件（summary.json + history/ + 看板）
├── .github/workflows/api-test.yml    # CI：PR 离线门禁 + 定时真实环境回归
├── config/setting.py                # 全局配置（全部支持环境变量覆盖）
├── data/                            # 测试数据（JSON）
│   ├── *_data.json                  #   各模块正向/边界/异常数据集
│   └── schemas/*.json               #   响应结构契约（JSON Schema）
├── tests/                           # 用例层（11 个模块文件）
│   └── unit/                        #   框架离线自测（mock HTTP，不依赖真实环境）
├── tools/                           # 数据维护、预检与仓库脚本
│   ├── check_login.py               #   账号预检（CI 前置卡点）
│   ├── check_goods_status.py        #   商品可用性预检
│   ├── fetch_valid_goods.py         #   抓取在售商品刷新测试数据
│   ├── ci_summary.py                #   CI 构建摘要（Actions / Jenkins 共用）
│   └── init_git.ps1                 #   仓库初始化 + 规范提交历史
├── reports/                         # 产物：dashboard.html（看板）/ summary.json / history/（历史归档）
├── pytest.ini  requirements.txt  run.py  Jenkinsfile  README.md
```

---

## 三、快速开始

```bash
# 1. 安装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/Mac

# 2. 凭证自检（公开沙箱账号可能被改密码或整体重置，务必先跑这一步）
.venv\Scripts\python.exe tools\check_login.py

# 3. 执行全量回归（同时产出 pytest-html 与 Allure 原始结果）
.venv\Scripts\python.exe run.py

# 4. 按需执行
.venv\Scripts\python.exe run.py -m smoke          # 冒烟用例
.venv\Scripts\python.exe run.py -m p0             # 核心链路
.venv\Scripts\python.exe run.py -m e2e            # E2E 闭环
.venv\Scripts\python.exe run.py -n 4              # 4 进程并行
.venv\Scripts\python.exe run.py --base-url http://127.0.0.1   # 切换被测环境
.venv\Scripts\python.exe run.py --allure-report   # 额外生成 Allure HTML（需 allure 命令行）

# 5. 查看报告
#   reports/dashboard.html       质量看板（自包含单文件，可离线打开，推荐先看这个）
#   reports/report.html          本次 pytest-html 详细报告
#   reports/summary.json         本次结构化结果（看板数据源）
#   reports/history/<运行编号>/   本次执行快照：report.html + summary.json + dashboard.html
#   reports/allure-results/      Allure 原始数据（allure serve reports/allure-results）
#   logs/autotest.log            全量请求/断言日志
```

常用 pytest 直连方式：`.venv\Scripts\python.exe -m pytest -m "p0 and not e2e" -k 登录`

---

## 四、用例设计

### 1. 数据驱动（DDT）

业务数据全部外置到 `data/*.json`，用例通过 `build_params(load_cases(...))` 自动参数化，
**新增/修改测试数据不需要改代码**。单个数据集内用 `group` 字段区分场景，示例（`data/cart_data.json`）：

```json
{
  "desc": "边界-购买数量为0被拦截",
  "group": "add",
  "goods_id": 12,
  "stock": 0,
  "expected_code": -1,
  "expected_msg": "购买数量有误"
}
```

- `expected_code`：精确业务码；填 `"not_0"` 表示只要求失败（用于提示语不稳定的场景）
- `known_defect`：标记「已知缺陷用例」，自动打 `xfail` 并携带缺陷单号，**缺陷被修复后会转为 XPASS 提醒**
- `schema`：指定 `data/schemas/*.json` 做响应结构契约校验
- `${USER}` / `${PWD}` / `${GOODS_ID}`：环境相关值用占位符，由 `core/data_loader.py` 自动替换为
  配置/环境变量中的值——**数据文件不硬编码账号密码**，沙箱改密码只需改一处配置

### 2. 用例类型

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| 正向 | 正常业务链路 | 登录成功、加购成功、提交订单成功 |
| 边界 | 参数极值与分页边界 | 数量 0/-1、超页码、超长关键字、200 字符密码 |
| 异常 | 参数缺失/非法/业务规则拦截 | 商品不存在、支付方式非法、待付款订单不能删除 |
| 安全 | 注入与越权 | SQL 注入式账号、伪造/缺失 token、XSS 关键字 |
| E2E | 跨模块闭环 + 数据一致性 | 登录→搜索→详情→加购→改数量→确认→提交→详情→取消 |

### 3. 环境隔离与数据清理

共享测试环境最大的坑是「脏数据」。项目做了三重保障：

1. 每个用例创建的地址/留言使用 `AutoTest + 时间戳 + 随机串` 唯一命名，避免相互干扰；
2. `temp_address` / `temp_order` / `clean_cart` 等 fixture 在 **teardown 自动回收**（删除地址、取消并删除订单、清空购物车），异常也不会漏清理；
3. 断言不依赖全局总数（如 `total == 1`），只断言自己创建的数据与业务规则，保证在多人共用的沙箱上可重复执行。

---

## 五、框架核心能力

### 1. 请求重试（可配置 + 幂等控制）—— `core/base_api.py`

- 触发条件：网络异常（ConnectionError/Timeout）、HTTP 5xx、约定的业务码（默认 -500）
- 退避策略：`retry_interval × backoff^(n-1)`，默认 2 次重试、0.5s 起、2 倍退避
- **幂等性保护**：下单、支付、评价、取消等写操作通过 `idempotent=False` 强制不重试，杜绝重复下单
- 每次尝试都会记录耗时、状态码、失败原因，重试过程在日志与 Allure 中完整可见

### 2. 统一 Token 鉴权封装 —— `core/auth.py`

- 接口对象只声明 `auth_type`（NONE / USER），**token 由框架按接口文档注入**（文档规定 token 走 GET 参数）
- 会话级缓存：一次登录全程复用，`tests/test_login.py::test_token_is_cached_and_reused` 用例专门守护这一点
- 失效自愈：业务码 `-400`（登录失效）时自动失效并重新登录重试一次
- 线程安全：`RLock` 保护，兼容 xdist/并发执行
- 日志脱敏：token 只保留首尾（`c2021a***3624`）

### 3. 统一断言层 —— `core/assert_helper.py`

`Assert.success / fail / code / msg_contains / schema / money / pagination / contains_keyword …`
失败信息自带业务 `msg`，不用再翻日志。`Assert.money` 处理浮点误差，`Assert.schema` 用 JSON Schema 做响应契约校验。

### 4. 响应容错

非 JSON / HTML 错误页 / 空响应不会抛裸异常，统一转换为框架错误码：
`-9998` 响应非 JSON、`-9999` 网络错误，并保留 `_raw`、`_http_status` 便于定位（见 `core/base_api.py::_parse`）。

### 5. 可观测性

- 每条请求输出：`POST api/cart/save -> code=0 msg=加入成功 (耗时65.9ms, 第1/1次)`
- Allure 附件：**可复现的 curl 命令 + 完整响应体**，失败用例可直接复制 curl 复现
- 失败自动分类：`reports/allure-results/categories.json` 把失败归为「产品缺陷 / 环境问题 / 用例问题」
- **Allure HTML 报告**（可选增强）：`python tools/get_allure.py` 把官方 CLI 装到项目内 `.tools/`（不污染系统 PATH；未安装时框架自动降级，用例照常执行），
  `python run.py --allure-report` 执行完自动渲染 `reports/allure-report/index.html`；CI 冒烟回归会把这份 HTML 作为 Artifact 上传
- 口径提示：allure-pytest 把 pytest 的 `xfailed` 计入 `skipped`（pytest 报 12 skipped + 7 xfailed ＝ Allure 报 19 skipped + 0 failed，总数都是 284）

### 6. 环境能力探测与按需跳过 —— `core/env_check.py`

会话开始先探测环境能力（登录可用性、关键路由、插件、后台入口），
`@pytest.mark.requires("coupon")` / `requires("merchant")` 的用例在能力缺失时**自动跳过并给出真实原因**，
报告里能看到「为什么没跑」，而不是静默通过或大面积报错。能力矩阵同时写入 Allure 环境信息、`reports/env_probe.json`
与质量看板的「环境能力矩阵」分区。

### 7. 结果归档与质量看板（历史报告不再被覆盖）—— `core/report_plugin.py` + `core/dashboard.py`

原来的痛点：pytest-html 每次执行都覆盖 `reports/report.html`，历史结果留不下来，
也就无法回答"这次回归比上次好还是差"。

现在的做法：

- 用 pytest hook 采集**结构化结果**（用例、模块、类型 marker、结论、耗时、跳过原因、缺陷单号），
  而不是事后解析文本报告——信息不丢失；
- 每次执行按**运行编号**归档到 `reports/history/<run_id>/`，内含 `report.html + summary.json + dashboard.html`，
  **互不覆盖**；默认保留最近 50 次，自动裁剪最旧的；
- 同时产出 `reports/dashboard.html` 质量看板（**自包含单文件、零外部依赖、可离线打开**）：
  本次概览（通过率 / 可执行通过率）、质量趋势（内联 SVG 折线 + 失败柱）、模块覆盖、
  **缺陷看板（由 xfail 守护用例自动汇总，缺陷修复后自动变"已修复"）**、
  失败与跳过诊断（产品缺陷 / 环境问题 / 用例问题 / 跳过）、环境能力矩阵、可搜索的用例明细；
- 看板会对自己做**数据自检**（分类合计是否等于总数、明细条数是否一致、跳过是否写了原因），
  结论直接显示在页面底部——展示层不能"说谎"；
- 归档与渲染失败只打印提示，**绝不影响测试结论**。

```powershell
python run.py --tag 发版前回归    # 给本次执行打标签，趋势图上可区分不同范围的执行
python run.py --open             # 执行完自动打开看板
python run.py --history-keep 100 # 历史结果保留 100 次
python run.py --no-dashboard     # 只归档结构化结果，不生成看板
```

看板与归档逻辑本身也有测试（`tests/test_report_tools.py`，22 条，含**与上次对比**与 **flaky 计算**），
其中包括"看板不得引用任何 CDN/外部资源"这条离线底线。

### 8. 框架自身的离线测试（双轨分层 + mock + 覆盖率门禁）—— `tests/unit/`

只测被测系统是不够的：**框架本身也会有 bug**（重试次数写错、异常被吞、token 未脱敏、占位符没替换）。
所以把用例分成两条轨：

| 轨道 | 内容 | 依赖 | 用途 |
| --- | --- | --- | --- |
| **离线（offline）** | `tests/unit/**` + 报告工具自测，用 `responses` **mock HTTP**，断言框架逻辑：重试策略、非 JSON/超时容错、幂等控制、token 缓存与失效重登、断言层报错信息、占位符展开、看板渲染 | 0 网络依赖 | CI 的 **PR 门禁**：秒级完成，不受别人沙箱可用性影响 |
| 集成（integration） | `tests/test_*.py` 真实接口用例 | 真实被测环境 | 定时回归、提交前的真实链路验证 |

```powershell
python run.py --offline        # 只跑离线自测（秒级，不访问任何网络）
python run.py -m smoke         # 跑真实环境冒烟
```

覆盖率门禁：CI 对**框架代码**（`core/`）设覆盖率红线，框架分支没被单测覆盖就会构建失败——
这条比"用例数量"更能说明测试代码本身是被验证过的。

**离线自测的产出不只是"绿"**：第一版离线套件就抓出 9 个框架自身缺陷，全部修复，
并把守护用例从"xfail 记录现状"改成"断言修复后行为"。这正是框架自测的价值——
框架悄悄吞异常、重试带旧 token、脱敏漏了响应体，被测系统的用例看起来照样是绿的。

| # | 框架缺陷（已修复） | 影响 | 处置 |
| --- | --- | --- | --- |
| 1 | **`-400` 失效重登是假的**：重试复用同一份 `params`，`_inject_token()` 见已有 token 直接返回，`invalidate()` 清了缓存却再没触发登录 | 日志写"已重新登录并重试"，实际仍发旧 token → 长跑回归会话过期会整批假失败，且排查方向被日志带偏 | 区分"框架注入 / 调用方传入"的 token，每轮重试前重新注入；日志改为如实描述；新增"只重登一次"守护用例 |
| 2 | 登录**响应体**未脱敏：`data.token` 明文写进 `last_exchange`，并作为 Allure 附件落盘 | 报告归档/外发即等于凭据泄露 | 响应体递归脱敏（`token`、`*token`、`pwd`、`password`） |
| 3 | `pwd` 长度 ≤3 时不做脱敏 | 短密码明文进 curl 与附件 | 去掉长度例外，统一脱敏 |
| 4 | `load_cases(group=...)` 分组名写错时静默返回**全部**用例（`filtered or cases`） | 用例"跑多了"却无任何提示，失败容易被算到错误的分组头上 | 改为报错并列出可用分组 |
| 5 | `unique()` 截断把时间戳+随机后缀整体砍掉 | `max_len` 接近前缀长度时返回值退化成常量，并发跑同一沙箱会互相覆盖数据 | 截断时优先保留唯一部分 |
| 6 | `CODE_NETWORK`(-9999) 口径分裂：文档写"网络异常 → -9999"，代码实际抛 `ApiError` | 上层写不出稳定的网络失败断言 | 统一口径：网络异常重试耗尽抛 `ApiError`（含尝试次数），`-9999` 只用于"请求未执行"的配置兜底，并补用例 |
| 7 | 环境探测把"探测失败"当成"能力可用"（非 JSON 响应、非 -10 错误码都算已安装） | 被 WAF 拦截或接口契约变更时误报"能力可用" → 相关用例假红，而不是按原因跳过 | 明确三态：未安装 / 探测失败（带 HTTP 状态与原因）/ 可用 |
| 8 | 探测异常只保留异常类名（如 `Timeout`），原因文本丢失且不记日志 | 环境问题无法定位 | 原因里带上异常原文，并写 warning 日志 |
| 9 | 说明性字段（`note`）也做占位符替换 | 账号密码被复制进用例数据，用例数据一旦进报告即泄露 | 说明性字段不参与占位符替换 |

覆盖率：离线套件对 `core/` 实测 **80%**（`base_api.py` 97%、`auth.py` 100%、`data_loader.py` 95%、`dashboard.py` 91%），
CI 门禁设 `--cov-fail-under=78`（留 2% 抖动余量；`allure_utils.py`、`report_plugin.py` 依赖 allure CLI
与真实 pytest 生命周期，离线套件覆盖不到，因此不设 85%）。

---

## 六、环境能力矩阵（当前沙箱实测）

| 能力 | 结果 | 实测依据 |
| --- | --- | --- |
| 站点可达 | ✅ | `GET /` → HTTP 200 |
| 用户登录 | ✅ | `api/user/login` → code=0 |
| 商品/搜索/购物车/订单/地址/消息/地区 | ✅ | 关键路由探测均 code=0 |
| 优惠券插件 | ❌ | `api/plugins/index?pluginsname=coupon` → `code=-10 应用未安装[coupon]` |
| 多商户插件 | ❌ | 同上，`应用未安装[shop]` |
| 商家后台 | ❌ | `admin.php?s=/admin/login/index` → HTML「非法访问」（后台入口被禁用） |

**因此**：优惠券（7 条）与商家后台（5 条）用例在当前沙箱被跳过，共 12 条。
代码与数据集已完整实现，在**安装了 coupons 插件 / 开放后台**的环境（本地部署或预发）上无需改代码即可执行：

```bash
python run.py --base-url http://your-shopxo-host     # 换环境即生效
```

跳过的同时仍保留了**可执行的数据契约校验**：如 `test_coupon_data_in_order_confirm` 会校验订单确认页
若下发 `plugins_coupon_data` 时的结构正确性，避免这部分完全无覆盖。

---

## 七、缺陷与风险清单（来自本轮自动化执行，均可复现）

| 缺陷单 | 现象 | 证据 | 对应用例（xfail 守护） |
| --- | --- | --- | --- |
| **BUG-CART-STOCK-001** | 加购接口不校验库存上限，存在超卖/恶意占库存风险 | `cart/save stock=999999` → `code=0 加入成功`；防线仅在下单时生效 | `test_cart_add[06]` |
| **BUG-ORDER-FILTER-001** | 订单列表状态筛选参数失效 | `status` 取 -1/0/1/2/3/4/5/6 返回同一份数据（total 恒为 230），且结果含与条件不符的状态 | `test_order_list_status_filter_should_narrow_results` |
| **BUG-ORDER-COMMENT-001** | 待付款订单评价接口「静默成功」 | 返回 `code=0 提交成功`，但订单 `is_comments` 仍为 0，评价未落库 | `test_order_comments_on_pending_should_be_rejected` |
| **BUG-GOODS-SPEC-001** | 畸形规格参数导致服务端 500 | `specdetail spec=[{"type":"choose","value":[{"id":"1"}]}]` → HTTP 500（非 JSON） | `test_spec_detail_malformed_spec_should_not_500` |
| **BUG-ADDR-TEL-001** | 地址手机号格式未校验（校验不一致） | `tel=abc` → `code=0 新增成功`；同样字段在留言接口会返回「联系电话有误」 | `test_address_invalid[03]` |
| **BUG-ADDR-DETAIL-001** | 地址详情缺少存在性校验 | 查询不存在的地址 ID → `code=0`（不报错），存在越权探测风险 | `test_address_invalid[04]` |
| **BUG-ANSWER-TEL-001** | 留言接口对空字符串电话不校验 | `tel=""` → `code=0 提交成功`；字段完全缺失时才拦截 | `test_answer_add_empty_tel_should_be_rejected` |

另外几处**已按真实语义落地的观察**（非缺陷，但用例已适配并在注释中说明）：

- `base.goods_count` / `common_cart_total` 的语义是**商品种类数（购物车行数）**，不是商品件数；
- 订单确认页对不存在的 `address_id` 不校验（沙箱站点类型为虚拟商品，允许无地址下单）；
- 登录密码未做 trim（`" huace_tester "` 也能登录成功）；
- `order/pay` 对「货到付款」订单返回的提示语为「订单id有误」，提示不准确；沙箱仅提供货到付款，在线支付成功链路无法验证。

---

## 八、CI/CD 集成（GitHub Actions + Jenkins）

两条流水线覆盖两种场景，都产出质量看板与历史归档：

**1) GitHub Actions（`.github/workflows/api-test.yml`，可直接演示）**

| 任务 | 触发 | 内容 | 为什么这么设计 |
| --- | --- | --- | --- |
| 离线框架自测（PR 门禁） | push / PR | 装依赖 → `pytest -m offline` → `core/` 覆盖率门禁 → 上传看板与 `coverage.xml` | 秒级、0 网络依赖：**不受别人沙箱可用性影响**，PR 反馈快且稳定 |
| 真实环境冒烟回归 | 工作日定时 / 手动 | 账号预检 → 安装 Allure CLI（`tools/get_allure.py`）→ `run.py -m smoke --allure-report` → 上传看板 + `history/` 归档 + **Allure HTML 报告** → 构建摘要写入 Actions 页面 | 环境不可用时只发 warning 并跳过，不把"环境问题"报成"测试失败" |

**2) Jenkins（`Jenkinsfile`，企业内常见形态）**

| 项目 | 配置 |
| --- | --- |
| 触发 | 代码提交自动触发 + **工作日每天 02:00 定时回归** + 手动传参 |
| 参数 | `BASE_URL`、`MARKER`（regression/smoke/p0/e2e）、`WORKERS`、`RERUN`、`GENERATE_ALLURE`、`TAG` |
| 阶段 | 代码检出 → 环境准备（venv + 依赖）→ 接口回归（打 CI 标签）→ 报告 |
| 报告 | 质量看板 + pytest-html 双发布，`reports/**`（含 `history/` 历史归档）与 `logs/` 归档 |
| 质量门禁 | pytest 退出码非 0 即构建失败；`tools/check_login.py`、`tools/check_goods_status.py` 作为环境/数据预检卡点 |
| 其他 | 构建历史保留 30 次、超时 30 分钟、禁止并发构建、Windows/Linux 节点自适应 |

本地模拟 CI 执行：`python run.py --offline`（门禁）／`python run.py -m regression -n 4 --rerun 1 --allure-report`（回归）

---

## 九、模块覆盖矩阵

| 模块 | 用例文件 | 用例数 | 覆盖要点 | 本环境结果 |
| --- | --- | --- | --- | --- |
| 用户登录 | `tests/test_login.py` | 14 | 正向、密码错误、账号不存在、空账号/空密码、缺 type、邮箱格式、超长密码、SQL 注入、token 有效性/缓存/伪造拦截 | 14 passed |
| 首页/用户中心 | `tests/test_user_center.py` | 7 | 首页聚合数据、消息分页、积分、留言提交与查询、字段校验差异、鉴权 | 6 passed / 1 xfail |
| 商品搜索 | `tests/test_search.py` | 10 | 关键字、无关键字、不存在关键字、超页码、特殊字符、超长关键字、分类筛选、分页一致性、搜索-详情一致性 | 10 passed |
| 商品 | `tests/test_goods.py` | 11 | 详情、免登录访问、收藏切换、规格类型、规格详情、多规格价格区间、畸形参数健壮性 | 10 passed / 1 xfail |
| 购物车 | `tests/test_cart.py` | 15 | 加购、数量边界、商品不存在、缺参、超库存、重复加购合并、金额计算、改数量、删除、清空、鉴权 | 14 passed / 1 xfail |
| 收货地址/地区 | `tests/test_address.py` | 9 | 增删改查生命周期、参数校验、详情、删除、地区二级联动、结构校验、鉴权 | 7 passed / 2 xfail |
| 订单 | `tests/test_order.py` | 18 | 确认页、金额一致性、提交、库存防线、详情、列表、状态机（待付款→已取消→删除）、收货、支付、评价 | 16 passed / 2 xfail |
| E2E 闭环 | `tests/test_order_e2e.py` | 1 | 登录→搜索→详情→加购→改数量→确认→提交→详情→购物车校验→取消→清理 | 1 passed |
| 优惠券 | `tests/test_coupon.py` | 8 | 可领券列表、领券、我的优惠券、下单用券数据契约 | 1 passed / 7 skipped |
| 商家后台 | `tests/test_merchant.py` | 5 | 后台登录、商品管理、订单管理、优惠券管理 | 5 skipped |
| **真实环境小计** | `tests/test_*.py` | **98** | 完整接口回归 + E2E 闭环 | **79 passed / 12 skipped / 7 xfailed** |
| 框架·请求驱动 | `tests/unit/test_base_api_unit.py` | 25 | 响应解析与 `_http_status`、非 JSON/结构异常容错、网络异常重试与退避、5xx 与业务码重试、幂等开关、公共参数位置、token 注入与**失效重登**、curl 生成与脱敏 | 25 passed |
| 框架·鉴权 | `tests/unit/test_auth_unit.py` | 19 | 登录与缓存、invalidate/force、账号切换、登录失败与无 token 报错、ADMIN 不支持密码登录、日志与请求上下文脱敏、并发只登录一次 | 19 passed |
| 框架·断言层 | `tests/unit/test_assert_helper_unit.py` | 41 | code/msg/schema/金额/分页的通过与失败信息、容差与非法入参、缺少 jsonschema 时的降级 | 41 passed |
| 框架·数据驱动 | `tests/unit/test_data_loader_unit.py` | 51 | 占位符展开与环境覆盖、加载条数=数据文件真实条数、分组过滤与报错、已知缺陷自动 xfail、`unique()` 唯一性、异常可定位 | 51 passed |
| 框架·环境探测 | `tests/unit/test_env_check_unit.py` | 28 | 离线零请求、缓存复用、插件三态判定、后台入口识别、异常不抛出且原因可读 | 28 passed |
| 报告工具（自测） | `tests/test_report_tools.py` | 22 | 汇总自检（总数一致性、跳过必须写原因）、看板渲染与**离线校验**（不得引用 CDN）、历史归档排序与裁剪、结论归并、**与上次对比**、**flaky 计算** | 22 passed |
| **离线自测小计** | `tests/unit/**` + 报告工具 | **186** | 全部 `responses` mock HTTP，0 网络依赖，约 1.3s 跑完 | **186 passed** |
| **合计** | | **284** | | **265 passed / 12 skipped / 7 xfailed** |

---

## 十、配置项（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SHOPXO_BASE_URL` | `http://shop-xo.hctestedu.com` | 被测环境地址 |
| `SHOPXO_ENV` | `test` | 环境标识（写入 Allure 环境信息） |
| `SHOPXO_USER` / `SHOPXO_PWD` | `huace_tester` / `123456` | 前台测试账号。**公开沙箱密码可能被他人修改或整体重置**（实测文档初始密码已失效），跑测试前用 `tools/check_login.py` 自检；建议在 CI 凭据中注入 |
| `SHOPXO_ADMIN_USER` / `SHOPXO_ADMIN_PWD` | `admin` / `admin123` | 商家后台账号 |
| `SHOPXO_TIMEOUT` | `15` | 请求超时（秒） |
| `SHOPXO_RETRY_TIMES` / `SHOPXO_RETRY_INTERVAL` | `2` / `0.5` | 重试次数 / 首次间隔 |
| `SHOPXO_GOODS_ID` | `12` | 默认测试商品 |
| `SHOPXO_DATA_PREFIX` | `AutoTest` | 测试数据统一前缀（便于识别与清理） |
| `SHOPXO_FORCE_FEATURES` | 未设置 | 设为 `1` 时强制执行被能力门控的用例（排查探测误判 / 验证门控用例本身） |
| `SHOPXO_OFFLINE` | 未设置 | 设为 `1` 时进入**离线模式**：不探测也不访问真实环境，只执行 `@pytest.mark.offline` 的框架自测用例（`run.py --offline` 等价） |

---

## 十一、工具脚本

| 脚本 | 用途 |
| --- | --- |
| `tools/check_login.py` | 凭证预检：确认测试账号能否登录，用于区分「环境凭证失效」和「用例失败」（CI 前置卡点，异常退出码 1） |
| `tools/check_goods_status.py` | 预检：测试数据引用的商品是否仍上架可售（CI 前置卡点，异常退出码 1） |
| `tools/fetch_valid_goods.py` | 数据维护：调用真实搜索接口抓取在售商品，刷新 `data/valid_goods.json`，避免手工编造测试数据 |
| `tools/get_allure.py` | 可选依赖安装：把官方 Allure CLI 装到项目内 `.tools/`（优先走 GitHub API 资产通道，适配受限网络；按 release 公布的 sha256 校验；装完自动 `allure --version` 自检 Java 环境）。用法：`python tools/get_allure.py`／`--version 2.46.1`／`--force`／`--check` |
| `tools/ci_summary.py` | 把 `reports/summary.json` 渲染成 Markdown 构建摘要（GitHub Actions Step Summary / Jenkins 构建说明共用同一份实现） |
| `tools/init_git.ps1` | 仓库初始化：检测 git（缺失时给出安装提示并不动作）→ 配置身份 → 按"配置/框架/接口层/用例/报告/单测/CI/工具/文档"分块提交，生成可回溯的规范提交历史。执行：`powershell -ExecutionPolicy Bypass -File tools\init_git.ps1` |

---

## 十二、成果与后续规划

**已落地**：分层框架 + 统一鉴权 + 请求重试 + 数据驱动 + 结构契约校验 + 环境自适应跳过 +
数据自动清理 + 结果归档与质量看板（趋势 / 缺陷看板 / **与上次对比** / **不稳定用例 flaky**）+
Allure/HTML 报告 + **框架离线自测（mock HTTP，0 网络依赖）** + **CI 质量门禁（GitHub Actions）** +
Jenkins 流水线 + 7 个可复现业务缺陷的自动化守护。

**后续可扩展**：
1. 数据工厂（Factory）统一造数与回收台账，支持多账号池（xdist 并发隔离）；
2. 安全专项体系化：水平越权（用 A 用户 token 操作 B 用户资源）、敏感信息回显、重复提交幂等；
3. 契约 / 属性测试：OpenAPI 驱动的参数与响应校验 + `schemathesis` 属性化模糊测试（自动挖掘畸形入参 500）；
4. 性能基线：核心接口 P95 响应时间阈值断言与慢接口统计，纳入回归门禁；
5. 质量门禁升级：`run.py --gate`（新增失败即失败）+ 企业微信/钉钉通知 + 质量周报自动生成；
6. 多客户端类型矩阵（`application_client_type` = weixin/ios/android/h5）兼容性用例。
