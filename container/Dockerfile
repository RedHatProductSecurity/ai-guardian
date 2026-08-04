# ai-guardian container image
#
# Multi-stage UBI-based container with ai-guardian and all headless-capable IDEs.
# Stage 1 (builder): installs all tools and dependencies
# Stage 2 (runtime): minimal image with only runtime artifacts
#
# Pull:
#   podman pull quay.io/redhatproductsecurity/ai-guardian:latest
#   podman pull quay.io/redhatproductsecurity/ai-guardian:dev
#
# Build locally:
#   Podman: podman build -t ai-guardian container/
#   Docker:  docker build -t ai-guardian container/
#   Podman: podman build --build-arg AI_GUARDIAN_VERSION=1.13.0 -t ai-guardian container/
#   Docker:  docker build --build-arg AI_GUARDIAN_VERSION=1.13.0 -t ai-guardian container/
#
# Run:
#   Podman: podman run -it -p 63152 ai-guardian
#   Docker:  docker run -it -p 63152 ai-guardian
#
#   With IDE:
#   Podman: podman run -it -p 63152 -e AI_GUARDIAN_IDE=opencode ai-guardian
#   Docker:  docker run -it -p 63152 -e AI_GUARDIAN_IDE=opencode ai-guardian
#
#   Find mapped port:
#   Podman: podman port <container-name>
#   Docker:  docker port <container-name>
#
# Using run.sh (handles both engines):
#   ./container/run.sh                         # uses podman by default
#   CONTAINER_ENGINE=docker ./container/run.sh # use docker instead
#
# Local wheel:
#   python -m build --wheel && cp dist/ai_guardian-*.whl container/vendor/
#   podman build --build-arg AI_GUARDIAN_VERSION=ai_guardian-1.13.0.dev0-py3-none-any.whl -t ai-guardian container/

# ============================================================
# Stage 1: builder — install everything, discard build tools
# ============================================================
FROM registry.access.redhat.com/ubi10/ubi-minimal:latest AS builder

ARG AI_GUARDIAN_VERSION=1.13.2
ARG UV_VERSION=0.11.16
ARG OPENCODE_VERSION=1.17.3
ARG GH_VERSION=2.74.1
ARG GLAB_VERSION=1.91.0

# Copy wheel files if present (Dockerfile included to guarantee COPY succeeds
# even when no .whl files exist in the build context)
COPY Dockerfile vendor/ai_guardian-*.whl /tmp/

# Build-time system packages
RUN microdnf install -y --nodocs \
        git curl bash tar gzip xz findutils sed \
        ca-certificates python3 python3-pip nodejs \
    && microdnf clean all

# uv — Python package manager
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
    | env INSTALLER_NO_MODIFY_PATH=1 UV_INSTALL_DIR=/usr/local/bin sh \
    && uv --version

# ai-guardian — from wheel if provided, otherwise PyPI
RUN echo "Installing ai-guardian: ${AI_GUARDIAN_VERSION}" \
    && case "${AI_GUARDIAN_VERSION}" in \
        *.whl) UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
               uv tool install "/tmp/${AI_GUARDIAN_VERSION}" \
               --with rapidocr-onnxruntime==1.4.4 ;; \
        *)     UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
               uv tool install "ai-guardian==${AI_GUARDIAN_VERSION}" \
               --with rapidocr-onnxruntime==1.4.4 ;; \
    esac \
    && chmod -R a+rX /opt/uv-tools \
    && rm -f /tmp/ai_guardian-*.whl /tmp/Dockerfile \
    && ln -sf /usr/local/bin/ai-guardian /usr/bin/ai-guardian \
    && (ai-guardian --version || echo "ai-guardian installed (version check skipped under emulation)")

# Replace opencv-python with headless variant (no X11/GUI deps needed).
# Order matters: uninstall first so cv2/ is removed, then headless recreates it.
RUN uv pip uninstall --python /opt/uv-tools/ai-guardian/bin/python3 opencv-python \
    && uv pip install --python /opt/uv-tools/ai-guardian/bin/python3 opencv-python-headless

# Secret scanners
RUN (ai-guardian scanner install gitleaks --use-pinned || true) \
    && test -x /usr/local/bin/gitleaks \
    && (ai-guardian scanner install betterleaks --use-pinned || true) \
    && test -x /usr/local/bin/betterleaks

# Node.js CLIs (installed to /opt/npm for predictable COPY paths)
RUN npm install -g --prefix /opt/npm @google/gemini-cli @openai/codex openclaw 2>/dev/null \
    && (PATH="/opt/npm/bin:$PATH" gemini --version 2>/dev/null || echo "Gemini CLI installed") \
    && (PATH="/opt/npm/bin:$PATH" codex --version 2>/dev/null || echo "Codex CLI installed") \
    && (PATH="/opt/npm/bin:$PATH" openclaw --version 2>/dev/null || echo "OpenClaw installed")

# OpenCode (Go binary — self-contained)
RUN mkdir -p /opt/opencode \
    && export HOME=/opt/opencode \
    && cd /opt/opencode \
    && curl -fsSL https://opencode.ai/install | VERSION=${OPENCODE_VERSION} bash \
    && chmod 755 /opt/opencode/.opencode/bin/opencode \
    && (/opt/opencode/.opencode/bin/opencode --version 2>/dev/null \
        || echo "OpenCode ${OPENCODE_VERSION} installed")

# Forge CLIs — gh and glab (static Go binaries)
RUN ARCH=$(uname -m | sed 's/aarch64/arm64/;s/x86_64/amd64/') \
    \
    # glab CLI
    && curl -fsSL -o /tmp/glab.tar.gz \
        "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_${ARCH}.tar.gz" \
    && tar -xzf /tmp/glab.tar.gz -C /usr/local bin/glab \
    && rm /tmp/glab.tar.gz \
    \
    # gh CLI (with checksum verification)
    && TARBALL="gh_${GH_VERSION}_linux_${ARCH}.tar.gz" \
    && curl -fsSL -o "/tmp/${TARBALL}" \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${TARBALL}" \
    && curl -fsSL -o /tmp/gh_checksums.txt \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
    && cd /tmp && grep -F " ${TARBALL}" gh_checksums.txt | sha256sum -c - \
    && tar -xzf "/tmp/${TARBALL}" -C /usr/local/bin --strip-components=2 \
        "gh_${GH_VERSION}_linux_${ARCH}/bin/gh" \
    && rm "/tmp/${TARBALL}" /tmp/gh_checksums.txt \
    \
    && (gh --version 2>/dev/null || echo "gh CLI installed") \
    && (glab --version 2>/dev/null || echo "glab CLI installed")


# ============================================================
# Stage 2: runtime — minimal image with only what's needed
# ============================================================
FROM registry.access.redhat.com/ubi10/ubi-minimal:latest

ARG AI_GUARDIAN_REST_PORT=63152

# Minimal runtime packages (no python3-pip, no uv, no X11 libs, no build tools)
RUN microdnf install -y --nodocs \
        shadow-utils git jq curl bash tar gzip findutils sed \
        ca-certificates hostname procps-ng \
        python3 nodejs \
    && microdnf clean all

# ai-guardian tool venv + trampoline binary
COPY --from=builder /opt/uv-tools /opt/uv-tools
COPY --from=builder /usr/local/bin/ai-guardian /usr/local/bin/
RUN ln -sf /usr/local/bin/ai-guardian /usr/bin/ai-guardian \
    && (ai-guardian --version || echo "ai-guardian installed (version check skipped under emulation)")

# Secret scanners (static Go binaries)
COPY --from=builder /usr/local/bin/gitleaks /usr/local/bin/
COPY --from=builder /usr/local/bin/betterleaks /usr/local/bin/

# Forge CLIs (static Go binaries)
COPY --from=builder /usr/local/bin/gh /usr/local/bin/
COPY --from=builder /usr/local/bin/glab /usr/local/bin/
RUN ln -sf /usr/local/bin/gh /usr/bin/gh

# Node.js CLIs — copy modules and create bin symlinks from package.json
COPY --from=builder /opt/npm/lib/node_modules /opt/npm/lib/node_modules
RUN node -e " \
    var fs=require('fs'),p=require('path'); \
    ['/opt/npm/lib/node_modules/@google/gemini-cli', \
     '/opt/npm/lib/node_modules/@openai/codex', \
     '/opt/npm/lib/node_modules/openclaw'].forEach(function(d){ \
        try{ \
            var pkg=JSON.parse(fs.readFileSync(d+'/package.json')); \
            var b=pkg.bin||{}; \
            if(typeof b==='string'){var o={};o[pkg.name.split('/').pop()]=b;b=o;} \
            Object.keys(b).forEach(function(n){ \
                var t=p.resolve(d,b[n]); \
                try{fs.unlinkSync('/usr/local/bin/'+n);}catch(e){} \
                fs.symlinkSync(t,'/usr/local/bin/'+n); \
                try{fs.chmodSync(t,493);}catch(e){} \
            }); \
        }catch(e){} \
    });" \
    && (gemini --version 2>/dev/null || echo "Gemini CLI available") \
    && (codex --version 2>/dev/null || echo "Codex CLI available") \
    && (openclaw --version 2>/dev/null || echo "OpenClaw available")

# Sandbox user
RUN groupadd -g 1000 sandbox \
    && useradd -m -u 1000 -g sandbox -d /sandbox sandbox \
    && ln -s /sandbox /home/sandbox \
    && rm -f /sandbox/.bash_profile \
    && echo 'export PATH="$HOME/.local/bin:$PATH"' > /sandbox/.bashrc \
    && chown sandbox:sandbox /sandbox/.bashrc \
    && echo 'printf "ai-guardian support container (built on '"$(date)"')\n\n"' \
        > /etc/profile.d/support_banner.sh

# Claude Code is proprietary (All Rights Reserved) — installed at runtime
# with user ToS consent via entrypoint.sh, not at build time.

# OpenCode binary
COPY --from=builder --chown=sandbox:sandbox /opt/opencode/.opencode /sandbox/.opencode

# Kiro CLI is AWS proprietary — installed at runtime with user ToS
# consent via entrypoint.sh, not at build time.

# Prepare config directories
RUN mkdir -p /sandbox/.claude /sandbox/.config /sandbox/.gemini /sandbox/.codex \
        /sandbox/.kiro /sandbox/.openclaw \
    && chown -R sandbox:sandbox /sandbox/.claude /sandbox/.config \
        /sandbox/.gemini /sandbox/.codex /sandbox/.kiro /sandbox/.openclaw

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV AI_GUARDIAN_REST_PORT=${AI_GUARDIAN_REST_PORT}
LABEL ai-guardian.daemon=true
LABEL ai-guardian.support-image=true

EXPOSE ${AI_GUARDIAN_REST_PORT}

WORKDIR /sandbox
USER sandbox
ENV HOME=/sandbox
ENV PATH="/sandbox/.local/bin:/sandbox/.opencode/bin:${PATH}"

ENTRYPOINT ["entrypoint.sh"]
CMD ["bash", "-l"]
