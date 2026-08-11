#!/bin/bash
# ============================================================
# 知衍 AI 知识管理系统 - Ubuntu 一键自动化部署脚本
# 使用方法: chmod +x deploy.sh && sudo ./deploy.sh
# 前置条件: project.tar.gz 与本脚本在同一目录下
# ============================================================

set -euo pipefail

# -------------------- 颜色定义 --------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# -------------------- 变量定义 --------------------
PROJECT_DIR="/root/zhiyang"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
STITCH_DIR="${PROJECT_DIR}/stitch_prd"
VENV_DIR="${BACKEND_DIR}/venv"
NGINX_WEB_ROOT="/var/www/zhiyan"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCHIVE="${SCRIPT_DIR}/project.tar.gz"

# -------------------- 工具函数 --------------------
log_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE}[步骤 $1]${NC} ${CYAN}$2${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

check_status() {
    if [ $? -ne 0 ]; then
        log_error "$1"
    fi
    log_info "$2 - 完成"
}

# -------------------- 权限检查 --------------------
if [ "$(id -u)" -ne 0 ]; then
    log_error "请使用 root 权限运行此脚本: sudo ./deploy.sh"
fi

# -------------------- 检查压缩包 --------------------
if [ ! -f "$ARCHIVE" ]; then
    log_error "未找到 project.tar.gz，请确保压缩包与本脚本在同一目录下: ${SCRIPT_DIR}"
fi

# ============================================================
# 步骤 0: 修复可能残留的 dpkg 锁
# ============================================================
log_step "0/12" "修复 dpkg 状态（清除残留锁和中断的安装）"

log_info "检查并修复 dpkg 中断问题 ..."
dpkg --configure -a 2>/dev/null || true
log_info "dpkg 状态修复完成"

log_info "清理 apt 缓存锁 ..."
rm -f /var/lib/apt/lists/lock 2>/dev/null || true
rm -f /var/cache/apt/archives/lock 2>/dev/null || true
rm -f /var/lib/dpkg/lock-frontend 2>/dev/null || true
rm -f /var/lib/dpkg/lock 2>/dev/null || true
log_info "锁文件清理完成"

# ============================================================
# 步骤 1: 替换 apt 源为阿里云镜像
# ============================================================
log_step "1/12" "配置 apt 阿里云镜像源"

log_info "备份原有 sources.list ..."
cp /etc/apt/sources.list /etc/apt/sources.list.bak.$(date +%Y%m%d%H%M%S) 2>/dev/null || true

UBUNTU_CODENAME=$(lsb_release -cs)
log_info "检测到 Ubuntu 代号: ${UBUNTU_CODENAME}"

cat > /etc/apt/sources.list << EOF
deb https://mirrors.aliyun.com/ubuntu/ ${UBUNTU_CODENAME} main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ ${UBUNTU_CODENAME}-security main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ ${UBUNTU_CODENAME}-updates main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ ${UBUNTU_CODENAME}-backports main restricted universe multiverse
EOF

log_info "更新 apt 缓存 ..."
apt update -y
check_status "apt 源更新失败" "apt 阿里云源配置"

# ============================================================
# 步骤 2: 安装系统基础工具
# ============================================================
log_step "2/12" "安装系统基础工具 (git vim curl nginx ffmpeg)"

apt install -y git vim curl nginx ffmpeg
check_status "基础工具安装失败" "系统基础工具安装"

# 确保 Nginx 开机自启
systemctl enable nginx
systemctl start nginx
check_status "Nginx 启动失败" "Nginx 启动并设置开机自启"

# ============================================================
# 步骤 3: 安装 Python 3.10
# ============================================================
log_step "3/12" "安装 Python 3.10 及 venv/pip"

# 检查是否已安装 Python 3.10
if python3.10 --version &>/dev/null; then
    log_info "Python 3.10 已安装: $(python3.10 --version)"
else
    apt install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt update -y
    apt install -y python3.10 python3.10-venv python3.10-dev
    check_status "Python 3.10 安装失败" "Python 3.10 安装"
fi

# 配置 pip 清华镜像源
log_info "配置 pip 清华镜像源 ..."
mkdir -p /root/.pip
cat > /root/.pip/pip.conf << 'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
log_info "pip 清华镜像源配置完成"

# ============================================================
# 步骤 4: 安装 Node.js 22 LTS
# ============================================================
log_step "4/12" "安装 Node.js 22 LTS"

# Vite 8 依赖的 Rolldown 需要 Node.js 20+，这里直接安装 22 LTS
NODE_MAJOR=22
NEED_INSTALL=false

if node --version &>/dev/null; then
    CURRENT_MAJOR=$(node -e "console.log(process.version.slice(1).split('.')[0])")
    if [ "$CURRENT_MAJOR" -ge "$NODE_MAJOR" ]; then
        log_info "Node.js 已安装且版本 >= ${NODE_MAJOR}: $(node --version)"
    else
        log_info "当前 Node.js $(node --version) 版本过低，需要升级到 ${NODE_MAJOR} LTS"
        NEED_INSTALL=true
        log_info "卸载旧版 Node.js ..."
        apt remove -y nodejs 2>/dev/null || true
    fi
else
    NEED_INSTALL=true
fi

if [ "$NEED_INSTALL" = true ]; then
    log_info "通过 NodeSource 安装 Node.js ${NODE_MAJOR} LTS ..."
    curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash -
    apt install -y nodejs
    check_status "Node.js ${NODE_MAJOR} 安装失败" "Node.js ${NODE_MAJOR} LTS 安装"
fi

log_info "Node.js 版本: $(node --version)"
log_info "npm 版本: $(npm --version)"

# 配置 npm 淘宝镜像源
log_info "配置 npm 淘宝镜像源 (npmmirror) ..."
npm config set registry https://registry.npmmirror.com
log_info "npm 镜像源配置完成"

# 安装 pnpm (前端使用 pnpm)
log_info "安装 pnpm ..."
npm install -g pnpm
check_status "pnpm 安装失败" "pnpm 安装"

# ============================================================
# 步骤 5: 创建项目目录并解压
# ============================================================
log_step "5/12" "创建项目目录并解压 project.tar.gz"

log_info "创建项目目录: ${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}"

log_info "解压 project.tar.gz 到 ${PROJECT_DIR} ..."
tar -xzf "${ARCHIVE}" -C "${PROJECT_DIR}"
check_status "解压 project.tar.gz 失败" "项目文件解压"

log_info "项目目录结构:"
ls -la "${PROJECT_DIR}/"

# 验证关键目录存在
if [ ! -d "$BACKEND_DIR" ]; then
    log_error "解压后未找到 backend 目录，请检查压缩包结构"
fi
if [ ! -d "$FRONTEND_DIR" ]; then
    log_error "解压后未找到 frontend 目录，请检查压缩包结构"
fi

# ============================================================
# 步骤 6: 配置后端环境变量
# ============================================================
log_step "6/12" "配置后端环境变量"

if [ -f "${BACKEND_DIR}/.env" ]; then
    log_info "已存在 .env 文件，备份为 .env.backup"
    cp "${BACKEND_DIR}/.env" "${BACKEND_DIR}/.env.backup.$(date +%Y%m%d%H%M%S)"
fi

log_info "生成生产环境 .env 配置 ..."
cat > "${BACKEND_DIR}/.env" << EOF
SECRET_KEY=$(python3.10 -c "import secrets; print(secrets.token_hex(32))")
DATABASE_PATH=./data/zhiyan.db
UPLOAD_DIR=./data/uploads
FRONTEND_ORIGIN=http://localhost

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_PROXY_URL=

HF_ENDPOINT=https://hf-mirror.com
HF_HOME=/tmp/zhiyan-huggingface
BGE_M3_MODEL=../data/bge-m3-int8
BGE_M3_DEVICE=cpu
BGE_M3_BACKEND=onnx
BGE_M3_ONNX_FILE=onnx/model_qint8_avx2.onnx

MILVUS_ENABLED=true
MILVUS_URI=
MILVUS_TOKEN=
MILVUS_DB_PATH=/tmp/zhiyan-milvus-standard.db
MILVUS_INDEX_TYPE=FLAT

FETCH_MCP_URL=
FETCH_MCP_TRANSPORT=auto
FETCH_MCP_TOKEN=
FETCH_MCP_TOOL=fetch
FETCH_MCP_TIMEOUT=30
FETCH_MCP_MAX_CHARS=100000
FETCH_DIRECT_TIMEOUT=15

OCR_MAX_IMAGE_BYTES=10485760
OCR_MAX_IMAGE_PIXELS=40000000
VIDEO_ANALYSIS_TIMEOUT=45
VIDEO_OCR_FRAME_COUNT=3
VIDEO_MAX_DURATION_SECONDS=1800
VIDEO_MAX_PIXELS=8294400
FFMPEG_BINARY=
FETCH_MCP_SSE_URL=
EOF

log_info "后端 .env 配置文件已生成"
log_warn "请根据实际情况编辑 ${BACKEND_DIR}/.env，填写 DEEPSEEK_API_KEY 等关键配置"

# ============================================================
# 步骤 7: 后端创建虚拟环境并安装依赖
# ============================================================
log_step "7/12" "后端创建虚拟环境并安装 Python 依赖"

cd "${BACKEND_DIR}"

log_info "创建 Python 虚拟环境 ..."
python3.10 -m venv "${VENV_DIR}"
check_status "虚拟环境创建失败" "虚拟环境创建"

log_info "激活虚拟环境并升级 pip ..."
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip
check_status "pip 升级失败" "pip 升级"

log_info "安装后端 Python 依赖 (使用清华镜像源) ..."
pip install -r requirements.txt
check_status "Python 依赖安装失败" "Python 依赖安装"

# 创建必要的运行时目录
log_info "创建运行时数据目录 ..."
mkdir -p "${BACKEND_DIR}/data/uploads"
log_info "运行时目录创建完成"

# 验证 BGE-M3 int8 模型已随压缩包部署
BGE_INT8_DIR="${PROJECT_DIR}/data/bge-m3-int8"
if [ -f "${BGE_INT8_DIR}/onnx/model_qint8_avx2.onnx" ]; then
    BGE_SIZE=$(du -sh "${BGE_INT8_DIR}" 2>/dev/null | cut -f1)
    log_info "BGE-M3 int8 ONNX 模型已就绪 (${BGE_SIZE})"
else
    log_warn "未检测到 BGE-M3 int8 模型，首次启动时将自动下载 (~2.2GB)"
fi

deactivate

# ============================================================
# 步骤 8: 配置后端 Systemd 服务
# ============================================================
log_step "8/12" "配置后端 Systemd 服务实现开机自启"

cat > /etc/systemd/system/zhiyan-backend.service << EOF
[Unit]
Description=Zhiyan AI Backend Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${BACKEND_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

log_info "重载 systemd 配置 ..."
systemctl daemon-reload

log_info "启动后端服务并设置开机自启 ..."
systemctl enable zhiyan-backend
systemctl restart zhiyan-backend
check_status "后端服务启动失败，请执行 journalctl -u zhiyan-backend -n 50 查看日志" "后端 Systemd 服务配置"

# 等待服务启动
sleep 3

# ============================================================
# 步骤 9: 前端安装依赖并构建
# ============================================================
log_step "9/12" "前端安装依赖并执行打包构建"

cd "${FRONTEND_DIR}"

# 注意: vite.config.js 中 publicDir 指向 ../stitch_prd
# 确保 stitch_prd 目录存在
if [ ! -d "$STITCH_DIR" ]; then
    log_warn "stitch_prd 目录不存在，着陆页静态资源可能缺失"
fi

log_info "安装前端依赖 (使用淘宝镜像源) ..."
pnpm install
check_status "前端依赖安装失败" "pnpm 依赖安装"

log_info "执行前端生产构建 ..."
pnpm run build
check_status "前端构建失败" "前端 Vite 构建"

log_info "构建产物目录:"
ls -la "${FRONTEND_DIR}/dist/" | head -20

# ============================================================
# 步骤 10: 配置 Nginx
# ============================================================
log_step "10/12" "配置 Nginx 反向代理与静态资源托管"

log_info "创建 Nginx Web 根目录 ..."
mkdir -p "${NGINX_WEB_ROOT}"

log_info "复制前端构建产物到 Nginx 托管目录 ..."
cp -r "${FRONTEND_DIR}/dist/"* "${NGINX_WEB_ROOT}/"
check_status "前端文件复制失败" "前端文件复制"

log_info "配置 Nginx ..."
cat > /etc/nginx/sites-available/zhiyan << 'EOF'
server {
    listen 80;
    server_name _;

    # 前端静态资源
    root /var/www/zhiyan;
    index index.html;

    # Gzip 压缩
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/json application/xml image/svg+xml;

    # 静态资源缓存
    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /monopoly-assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /zhiyan_logo/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    # SPA 路由回退 (所有非文件请求返回 index.html)
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

# 启用站点配置
log_info "启用 Nginx 站点配置 ..."
ln -sf /etc/nginx/sites-available/zhiyan /etc/nginx/sites-enabled/zhiyan

# 移除默认站点配置
rm -f /etc/nginx/sites-enabled/default

# 测试 Nginx 配置
log_info "测试 Nginx 配置语法 ..."
nginx -t
check_status "Nginx 配置语法检查失败" "Nginx 配置语法检查"

# 重载 Nginx
log_info "重载 Nginx ..."
systemctl reload nginx
check_status "Nginx 重载失败" "Nginx 重载"

# ============================================================
# 步骤 11: 最终验证
# ============================================================
log_step "11/12" "部署验证"

VERIFY_OK=true

# 验证后端服务
log_info "验证后端服务 (http://127.0.0.1:8000/api/health) ..."
if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health | grep -q "200"; then
    echo -e "${GREEN}  ✓ 后端服务运行正常${NC}"
    BACKEND_RESPONSE=$(curl -s http://127.0.0.1:8000/api/health)
    echo -e "  ${CYAN}${BACKEND_RESPONSE}${NC}"
else
    echo -e "${RED}  ✗ 后端服务未正常响应${NC}"
    VERIFY_OK=false
fi

# 验证 Nginx 前端
log_info "验证前端页面 (http://127.0.0.1/) ..."
if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1/ | grep -q "200"; then
    echo -e "${GREEN}  ✓ 前端页面访问正常${NC}"
else
    echo -e "${RED}  ✗ 前端页面访问失败${NC}"
    VERIFY_OK=false
fi

# 验证 API 代理
log_info "验证 API 代理 (http://127.0.0.1/api/health) ..."
if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1/api/health | grep -q "200"; then
    echo -e "${GREEN}  ✓ Nginx API 代理正常${NC}"
else
    echo -e "${RED}  ✗ Nginx API 代理失败${NC}"
    VERIFY_OK=false
fi

# 验证 systemd 服务状态
log_info "验证 systemd 服务状态 ..."
if systemctl is-active --quiet zhiyan-backend; then
    echo -e "${GREEN}  ✓ zhiyan-backend 服务运行中${NC}"
else
    echo -e "${RED}  ✗ zhiyan-backend 服务未运行${NC}"
    VERIFY_OK=false
fi

if systemctl is-enabled --quiet zhiyan-backend; then
    echo -e "${GREEN}  ✓ zhiyan-backend 已设置开机自启${NC}"
else
    echo -e "${RED}  ✗ zhiyan-backend 未设置开机自启${NC}"
    VERIFY_OK=false
fi

# ============================================================
# 部署结果
# ============================================================
echo ""
echo -e "${BLUE}============================================================${NC}"

if [ "$VERIFY_OK" = true ]; then
    echo -e "${GREEN}  ✓ 知衍 AI 知识管理系统部署成功！${NC}"
    echo ""
    echo -e "  访问地址:  ${CYAN}http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'YOUR_SERVER_IP')${NC}"
    echo -e "  API 文档:  ${CYAN}http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'YOUR_SERVER_IP')/api/docs${NC}"
    echo ""
    echo -e "  项目目录:    ${PROJECT_DIR}"
    echo -e "  后端日志:    journalctl -u zhiyan-backend -f"
    echo -e "  Nginx 配置:  /etc/nginx/sites-available/zhiyan"
    echo -e "  后端配置:    ${BACKEND_DIR}/.env"
    echo ""
    echo -e "${YELLOW}  ⚠  请及时编辑 ${BACKEND_DIR}/.env 填写 DEEPSEEK_API_KEY 等生产配置${NC}"
else
    echo -e "${RED}  ✗ 部署过程中部分验证失败，请检查上述错误信息${NC}"
    echo ""
    echo -e "  排查命令:"
    echo -e "  后端日志:    journalctl -u zhiyan-backend -n 50"
    echo -e "  后端状态:    systemctl status zhiyan-backend"
    echo -e "  Nginx 日志:  tail -f /var/log/nginx/error.log"
fi

echo -e "${BLUE}============================================================${NC}"
