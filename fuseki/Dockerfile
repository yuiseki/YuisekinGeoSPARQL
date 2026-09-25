FROM eclipse-temurin:21-jre@sha256:49e21e16e3c86eb7816a44a67549910ed090fbeb40c29c525d58bf5e02e91b0f

# One jar. Since Jena 5 the standalone Fuseki server bundles the GeoSPARQL
# module, so there is no dependency tree to resolve and nothing to drift.
ARG JENA_VERSION=6.2.0
ARG JENA_SHA256=2c92c598e65ab69d99820052e05f4277ed1d77980a8845f87545ad35b71a76ee
ARG JENA_URL=https://repo1.maven.org/maven2/org/apache/jena/jena-fuseki-server/6.2.0/jena-fuseki-server-6.2.0.jar

WORKDIR /fuseki
RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    curl -fsSL -o fuseki-server.jar "$JENA_URL"; \
    echo "${JENA_SHA256}  fuseki-server.jar" | sha256sum -c -; \
    rm -rf /var/lib/apt/lists/*
# curl stays: the healthcheck uses it, and a healthcheck that cannot run is a
# service that never becomes healthy and a test run that never starts.

COPY config-head.ttl entrypoint.sh /fuseki/
RUN chmod +x /fuseki/entrypoint.sh
EXPOSE 3030
ENTRYPOINT ["/fuseki/entrypoint.sh"]
