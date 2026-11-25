FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cowsay fortune-mod fortunes-min netcat-openbsd tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 wisecow \
    && useradd --uid 10001 --gid wisecow --home-dir /app --create-home --shell /usr/sbin/nologin wisecow

# debian installs fortune and cowsay in /usr/games
ENV PATH="/usr/games:${PATH}"

COPY --chmod=755 wisecow.sh /usr/local/bin/wisecow.sh

USER 10001
WORKDIR /app
EXPOSE 4499

ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["wisecow.sh"]
