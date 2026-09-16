// ShopXO 电商平台 API 自动化测试流水线
// 触发方式：代码提交自动触发 + 每天凌晨定时回归 + 支持手动传参执行
// 说明：Windows / Linux 构建节点均可运行（自动选择 python 解释器）
pipeline {
    agent any

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    parameters {
        string(name: 'BASE_URL', defaultValue: 'http://shop-xo.hctestedu.com', description: '被测环境地址')
        choice(name: 'MARKER', choices: ['regression', 'smoke', 'p0', 'e2e', 'not merchant'], description: '用例范围')
        string(name: 'WORKERS', defaultValue: '4', description: '并行进程数')
        string(name: 'RERUN', defaultValue: '1', description: '失败重跑次数（仅幂等接口生效）')
        booleanParam(name: 'GENERATE_ALLURE', defaultValue: true, description: '是否生成 Allure HTML 报告')
    }

    triggers {
        // 工作日每天 02:00 自动执行全量回归
        cron('H 2 * * 1-5')
    }

    environment {
        SHOPXO_BASE_URL = "${params.BASE_URL}"
        SHOPXO_ENV = 'ci'
        PYTHONUNBUFFERED = '1'
        PYTHONUTF8 = '1'
    }

    stages {
        stage('代码检出') {
            steps {
                echo "开始执行 ShopXO 接口自动化测试，环境：${params.BASE_URL}"
                checkout scm
            }
        }

        stage('环境准备') {
            steps {
                script {
                    def python = isUnix() ? 'python3' : 'python'
                    if (isUnix()) {
                        sh "${python} -m venv .venv || true"
                        sh ". .venv/bin/activate && pip install -U pip && pip install -r requirements.txt"
                    } else {
                        bat "${python} -m venv .venv"
                        bat ".venv\\Scripts\\python.exe -m pip install -U pip"
                        bat ".venv\\Scripts\\python.exe -m pip install -r requirements.txt"
                    }
                }
            }
        }

        stage('接口回归测试') {
            steps {
                script {
                    def python = isUnix() ? '.venv/bin/python' : '.venv\\Scripts\\python.exe'
                    // --tag：给本次执行打标签，便于质量看板区分不同范围的执行趋势
                    def cmd = "${python} run.py -m \"${params.MARKER}\" -n ${params.WORKERS} --rerun ${params.RERUN} --tag \"CI-${params.MARKER}\" --history-keep 50"
                    if (params.GENERATE_ALLURE) {
                        cmd += " --allure-report"
                    }
                    if (isUnix()) {
                        sh cmd
                    } else {
                        bat cmd
                    }
                }
            }
        }
    }

    post {
        always {
            script {
                // 归档测试报告与日志（reports/history/ 也在其中，历史结果不会被覆盖），失败时可直接从构建页面下载
                archiveArtifacts artifacts: 'reports/**/*,logs/**/*', allowEmptyArchive: true, fingerprint: true

                // 质量看板（自包含单文件，趋势/缺陷看板/模块覆盖）
                if (fileExists('reports/dashboard.html')) {
                    publishHTML(target: [
                        allowMissing: true,
                        alwaysLinkToLastBuild: true,
                        keepAll: false,
                        reportDir: 'reports',
                        reportFiles: 'dashboard.html',
                        reportName: '接口自动化质量看板'
                    ])
                }

                if (fileExists('reports/report.html')) {
                    publishHTML(target: [
                        allowMissing: true,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: 'reports',
                        reportFiles: 'report.html',
                        reportName: '接口自动化测试报告(pytest-html)'
                    ])
                }
            }
            echo "流水线结束，构建结果：${currentBuild.currentResult}"
        }
        success {
            echo '回归通过：核心接口链路无异常'
        }
        failure {
            echo '回归失败：请查看 Allure 报告与 logs/autotest.log 定位问题'
        }
    }
}
