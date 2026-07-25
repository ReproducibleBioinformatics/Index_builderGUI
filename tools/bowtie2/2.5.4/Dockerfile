# bowtie2 2.5.4 - official precompiled Linux binaries from the tagged GitHub
# release. The wrapper scripts are Python 3; the binaries need only glibc.
FROM debian:bookworm-slim
ARG TOOL_VERSION=2.5.4
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget unzip python3 \
 && wget -qO /tmp/bt2.zip "https://github.com/BenLangmead/bowtie2/releases/download/v${TOOL_VERSION}/bowtie2-${TOOL_VERSION}-linux-x86_64.zip" \
 && unzip -q /tmp/bt2.zip -d /opt \
 && rm -f /tmp/bt2.zip \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/bowtie2-${TOOL_VERSION}-linux-x86_64:$PATH
RUN bowtie2-build --version | head -1
