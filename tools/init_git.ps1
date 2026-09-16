<#
.SYNOPSIS
    初始化 Git 仓库，并按"逻辑分层"做首次提交（生成规范、可回溯的提交历史）。

.DESCRIPTION
    为什么要分多次提交：一次 git add . && commit 的历史看不出架构演进，code review 也无从下手。
    这里按 配置 → 框架 → 接口层 → 用例 → 报告看板 → 离线单测 → CI → 工具 → 文档 切分，
    每条消息都用 Conventional Commits 前缀（chore/feat/test/ci/docs）。

    脚本是幂等的：检测到已存在 .git 就直接退出，不会破坏已有历史。

.EXAMPLE
    pwsh -File tools\init_git.ps1
    # 或
    powershell -ExecutionPolicy Bypass -File tools\init_git.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ---------------------------------------------------------------- 前置检查
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[X] 未检测到 git，无法初始化仓库。安装方式（任选其一）：' -ForegroundColor Red
    Write-Host '    1) winget install --id Git.Git -e'
    Write-Host '    2) scoop install git'
    Write-Host '    3) 手动下载：https://git-scm.com/download/win'
    Write-Host '  安装后请重开终端，再执行：pwsh -File tools\init_git.ps1'
    exit 1
}
Write-Host ("[√] git 版本：" + (git --version))

if (Test-Path (Join-Path $root '.git')) {
    Write-Host '[!] 仓库已存在（.git 目录），不重复初始化。当前历史：' -ForegroundColor Yellow
    git log --oneline -n 15
    exit 0
}

# ---------------------------------------------------------------- 身份配置
if (-not (git config --get user.name)) {
    git config user.name 'ShopXO AutoTest'
    Write-Host '[!] 已写入占位 user.name，请改成你自己的：git config user.name "你的名字"' -ForegroundColor Yellow
}
if (-not (git config --get user.email)) {
    git config user.email 'shopxo-autotest@example.com'
    Write-Host '[!] 已写入占位 user.email，请改成你自己的：git config user.email "you@example.com"' -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 初始化
git init -q
git symbolic-ref HEAD refs/heads/main     # 默认分支 main（兼容旧版 git）
Write-Host '[√] 已初始化仓库，默认分支 main'

function Commit-Chunk {
    <# 只提交真实存在的路径，空分块自动跳过（脚本可重复运行而不报错） #>
    param([string]$Message, [string[]]$Paths)

    $existing = @($Paths | Where-Object { Test-Path $_ })
    if ($existing.Count -eq 0) {
        Write-Host ("[跳过] " + $Message + "（路径不存在）") -ForegroundColor DarkGray
        return
    }
    git add -- $existing
    if (-not (git diff --cached --quiet)) {
        git commit -q -m $Message
        Write-Host ("[提交] " + $Message) -ForegroundColor Green
    } else {
        Write-Host ("[无变更] " + $Message) -ForegroundColor DarkGray
    }
}

# ---------------------------------------------------------------- 分块提交
Commit-Chunk 'chore: 初始化仓库（依赖清单、pytest 配置、忽略规则）' @(
    '.gitignore', 'requirements.txt', 'pytest.ini'
)

Commit-Chunk 'feat(config): 配置层与数据层（环境变量全覆盖 + DDT 用例集 + JSON Schema 契约）' @(
    'config', 'data'
)

Commit-Chunk 'feat(core): 框架层（请求驱动/重试、统一鉴权、断言层、数据驱动、环境能力探测）' @(
    'core/base_api.py', 'core/auth.py', 'core/assert_helper.py', 'core/data_loader.py',
    'core/env_check.py', 'core/logger.py', 'core/allure_utils.py', 'core/__init__.py'
)

Commit-Chunk 'feat(api): 接口对象层（登录/商品/搜索/购物车/订单/地址/用户中心/优惠券/商家后台）' @(
    'api_objects'
)

Commit-Chunk 'test(api): 接口用例 98 条（正向/边界/异常/安全/E2E + 环境能力自适应跳过）' @(
    'tests/conftest.py', 'tests/test_login.py', 'tests/test_user_center.py', 'tests/test_search.py',
    'tests/test_goods.py', 'tests/test_cart.py', 'tests/test_address.py', 'tests/test_order.py',
    'tests/test_order_e2e.py', 'tests/test_coupon.py', 'tests/test_merchant.py'
)

Commit-Chunk 'feat(report): 结果归档插件与质量看板（历史不覆盖、趋势/缺陷看板/对比/flaky）' @(
    'core/report_plugin.py', 'core/dashboard.py', 'tests/test_report_tools.py'
)

Commit-Chunk 'feat(cli): 统一执行入口 run.py（标签/离线/覆盖率/历史裁剪等参数透传 + 执行结束打印质量看板路径）' @(
    'run.py'
)

Commit-Chunk 'test(unit): 框架离线自测（mock HTTP，0 网络依赖，支撑 PR 门禁与覆盖率门禁）' @(
    'tests/unit'
)

Commit-Chunk 'ci: GitHub Actions 流水线（离线门禁 + 定时真实环境回归）与 Jenkinsfile' @(
    '.github', 'Jenkinsfile'
)

Commit-Chunk 'feat(tools): 维护与预检脚本（账号预检、商品状态、有效商品抓取、CI 摘要）' @(
    'tools'
)

Commit-Chunk 'docs: README、测试执行手册与面试要点文档' @(
    'README.md', 'docs'
)

Commit-Chunk 'chore: 提交质量看板快照（自包含单文件，便于直接查看效果）' @(
    'reports/dashboard.html'
)

# ---------------------------------------------------------------- 结果
Write-Host ''
Write-Host '================ 提交历史 ================' -ForegroundColor Cyan
git log --oneline
Write-Host ''
Write-Host '================ 后续步骤 ================' -ForegroundColor Cyan
Write-Host '1) 在 GitHub 新建空仓库（不要勾选 README/.gitignore，避免冲突）'
Write-Host '2) 关联远程并推送：'
Write-Host '     git remote add origin https://github.com/jialinj505-crypto/ShopXO-API-Automation-Test.git'
Write-Host '     git push -u origin main'
Write-Host '3) 推送后到 Actions 页面看首次运行（README 顶部徽章已指向本仓库）'
Write-Host '4) 首次运行若提示 permission denied：确认已登录 GitHub（gh auth login 或配置 PAT）'
Write-Host ''
Write-Host ("[√] 完成，仓库文件数：" + (git ls-files | Measure-Object).Count)
