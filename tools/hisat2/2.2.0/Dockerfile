# hisat2 2.2.0 - compiled from the tagged GitHub source.
#
# Only the index builders are compiled (hisat2-build-s and hisat2-build-l), not
# the aligners: this service builds indexes and never aligns, and a full "make"
# takes many minutes while these two take about two. hisat2-build is a Python
# wrapper that dispatches to them, run through python-is-python3; the splice-site
# and exon extract scripts are Python 3. The binaries link only pthread.
FROM debian:bookworm-slim
ARG TOOL_VERSION=2.2.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates wget make g++ zlib1g-dev python3 python-is-python3 \
 && wget -qO /tmp/hisat2.tar.gz "https://github.com/DaehwanKimLab/hisat2/archive/refs/tags/v${TOOL_VERSION}.tar.gz" \
 && tar -xzf /tmp/hisat2.tar.gz -C /opt \
 && make -C /opt/hisat2-${TOOL_VERSION} -j"$(nproc)" hisat2-build-s hisat2-build-l \
 && rm -f /tmp/hisat2.tar.gz \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/hisat2-${TOOL_VERSION}:$PATH
RUN hisat2-build --version \
 && test -f /opt/hisat2-${TOOL_VERSION}/hisat2_extract_splice_sites.py \
 && test -f /opt/hisat2-${TOOL_VERSION}/hisat2_extract_exons.py
