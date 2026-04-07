FROM python:3.14-slim-trixie

ARG EXTRAS="default"

ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update &&  \
    apt-get install -y --no-install-recommends \
        qemu-system-x86 \
        qemu-utils \
        ovmf &&  \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies before copying the code (to leverage caching):
COPY pyproject.toml .
RUN pip install ".[$EXTRAS]"

# Copy the project itself:
COPY miniqa ./miniqa

RUN pip install ".[$EXTRAS]"  # install again, this time for the sources

RUN rm -r ./miniqa

# Install webui frontend dependencies and download OCR models, if supported:
ENV MINIQA_OCR_MODEL_CACHE_DIR=/miniqa_container_cache/ocr_models
RUN mkdir -p $MINIQA_OCR_MODEL_CACHE_DIR
RUN echo 'image: dummy' > miniqa.yml && \
    MINIQA_SETUP_SKIP_CONFIRM=true python -m miniqa -vv setup && \
    rm miniqa.yml

# Make the webui accessible from the host:
ENV MINIQA_WEBUI_HOST=0.0.0.0
ENV MINIQA_WEBUI_PORT=8080
ENV MINIQA_WEBUI_VNC_HOST=0.0.0.0
ENV MINIQA_WEBUI_VNC_PORT=6080

EXPOSE 8080 8080
EXPOSE 6080 6080

RUN mkdir -p /tests
WORKDIR /tests

ENTRYPOINT ["python", "-m", "miniqa"]
