##### base image -- has the Python interpreter installed
FROM python:3.8.3-alpine3.12 AS base_image

ARG CONTAINER_USER
ARG CONTAINER_UID

RUN id -u ${CONTAINER_USER} || adduser --uid ${CONTAINER_UID} --disabled-password ${CONTAINER_USER}

ARG TARGET_EYE_REPO=/usr/local/lib/target-eye

##### build image
FROM base_image AS deps

RUN apk add --no-cache -qU bzip2-dev gcc g++ git make libffi-dev openssh openssl-dev readline-dev zlib-dev

# Copy the Target-eye code over
ARG TARGET_EYE_BRANCH
RUN git clone --depth 1 -b ${TARGET_EYE_BRANCH} git@github.com:flightaware/target-eye.git ${TARGET_EYE_REPO} && \
    chown -R ${CONTAINER_USER} ${TARGET_EYE_REPO}

WORKDIR "${TARGET_EYE_REPO}"

# Build all the Python deps
USER ${CONTAINER_USER}
COPY .env .env
RUN make docker-setup

ENTRYPOINT ["venv/bin/python3"]
CMD ["-m", "fa_target_eye"]

##### prod image -- only copy from deps what is needed
FROM base_image AS prod

COPY --chown=${CONTAINER_USER}: --from=deps ${TARGET_EYE_REPO} ${TARGET_EYE_REPO} 

USER ${CONTAINER_USER}
WORKDIR "${TARGET_EYE_REPO}"

ENTRYPOINT ["venv/bin/python3"]
CMD ["-m", "fa_target_eye"]

ARG BUILD_DATE
ARG IMAGE
LABEL \
    org.label-schema.build-date = $BUILD_DATE \
    org.label-schema.name = $IMAGE \
    org.label-schema.vcs-url = "https://github.com/flightaware/target-eye" \
    org.label-schema.description = "File-based dynamic target discovery REST API for Prometheus"
