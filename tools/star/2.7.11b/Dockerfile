# STAR 2.7.11b - precompiled static Linux binary taken from the tagged GitHub tree.
# The Linux_x86_64_static build is fully static, so it needs no runtime libs.
# ADD fetches through the Docker daemon, which works during on-the-fly builds.
FROM debian:bookworm-slim
ARG TOOL_VERSION=2.7.11b
ADD https://raw.githubusercontent.com/alexdobin/STAR/${TOOL_VERSION}/bin/Linux_x86_64_static/STAR /usr/local/bin/STAR
RUN chmod +x /usr/local/bin/STAR && STAR --version
