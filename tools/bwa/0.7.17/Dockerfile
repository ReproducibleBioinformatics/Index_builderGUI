# bwa 0.7.17 - compiled from the tagged GitHub source.
#
# -fcommon is required for 0.7.17: its rle.h declares rle_auxtab without extern,
# which GCC 10 and later reject by default (-fno-common became the default), and
# the link fails with "multiple definition of rle_auxtab". Upstream fixed the
# header in 0.7.18; the flag is harmless there, so one recipe serves both.
#
# Runtime needs only zlib, which is already in the base image.
FROM debian:bookworm-slim
ARG TOOL_VERSION=0.7.17
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget make gcc zlib1g-dev \
 && wget -qO /tmp/bwa.tar.gz "https://github.com/lh3/bwa/archive/refs/tags/v${TOOL_VERSION}.tar.gz" \
 && tar -xzf /tmp/bwa.tar.gz -C /tmp \
 && make -C /tmp/bwa-${TOOL_VERSION} -j"$(nproc)" \
      CFLAGS="-g -Wall -Wno-unused-function -O2 -fcommon" \
 && cp /tmp/bwa-${TOOL_VERSION}/bwa /usr/local/bin/bwa \
 && chmod +x /usr/local/bin/bwa \
 && rm -rf /tmp/bwa* /var/lib/apt/lists/* \
 && bwa 2>&1 | grep -i "^Version:"
