FROM python:3.11-slim

WORKDIR /app

# 换国内镜像源加速
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 分步安装，降低失败风险
RUN pip install --no-cache-dir flask flask-cors pandas requests
RUN pip install --no-cache-dir akshare

# 复制代码
COPY . .

# 建立必要目录
RUN mkdir -p logs data knowledge_base/signals dashboard

EXPOSE 8080

CMD ["python", "server.py"]
