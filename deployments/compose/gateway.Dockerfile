FROM golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -o /gateway ./cmd/gateway
RUN CGO_ENABLED=0 go build -trimpath -o /healthcheck ./cmd/healthcheck
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
ARG SOURCE_REVISION=unknown
ARG SERVICE_ROLE=gateway
COPY --from=build /gateway /gateway
COPY --from=build /healthcheck /healthcheck
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      com.speech-platform.service-role=${SERVICE_ROLE} \
      com.speech-platform.service="gateway" \
      com.speech-platform.runtime-variant="foundation"
ENTRYPOINT ["/gateway"]
