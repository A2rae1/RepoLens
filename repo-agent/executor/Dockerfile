FROM python:3.12.9-slim
# Trusted runner dependencies installed before mounting any untrusted repository.
RUN python -m pip install --no-cache-dir pytest==8.3.4 flit_core==3.10.1 colorama==0.4.6
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
WORKDIR /work
