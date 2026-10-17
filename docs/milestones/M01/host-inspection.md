# M01 target-host inspection procedure

This is a manual, read-only preflight for the user to run on `llm`. Codex must not connect to the host automatically. Do not run deployment commands during this inspection. The commands below only query host, Docker, socket, GPU, memory and disk state; they do not start, stop, or modify services.

Run from a workstation with the operator's existing SSH configuration:

```sh
ssh llm 'bash -s' <<'REMOTE_READ_ONLY'
printf '\n== Host ==\n'
hostname
date -Is

printf '\n== Running containers and published ports ==\n'
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
printf '\n== Compose projects ==\n'
docker compose ls
printf '\n== Container project, network and port details ==\n'
for id in $(docker ps -q); do
  docker inspect --format '{{.Name}} project={{index .Config.Labels "com.docker.compose.project"}} networks={{json .NetworkSettings.Networks}} ports={{json .NetworkSettings.Ports}}' "$id"
done

printf '\n== TCP listeners (review the configured Gateway host port; default is 8080) ==\n'
ss -ltnp
printf '\n== Docker published bindings (also shown above) ==\n'
docker ps --format '{{.Names}} {{.Ports}}'

printf '\n== NVIDIA GPU visibility on host ==\n'
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
printf '\n== Docker runtimes ==\n'
docker info --format 'default={{.DefaultRuntime}} runtimes={{json .Runtimes}}'

printf '\n== RAM ==\n'
free -h
printf '\n== Disk space ==\n'
df -h /
df -h /var/lib/docker 2>&1 || true
printf '\n== Docker storage usage (read-only report) ==\n'
docker system df

printf '\n== Ollama/Dify service and network isolation evidence ==\n'
docker network ls
systemctl list-units --type=service --state=running 2>/dev/null | grep -Ei 'ollama|dify' || true
REMOTE_READ_ONLY
```

If the proposed Gateway host port is not 8080, inspect that port in the `ss` output and Docker published bindings as well. Do not attempt to reserve it or start a test listener. An empty listener result only describes the instant of inspection and does not guarantee future availability.

Review the container list and details for existing Ollama and Dify services. Record their Compose project labels, networks and published ports, then confirm the proposed Speech Platform deployment uses its own Compose project and that only the Gateway publishes a host port. The M01 Compose skeleton keeps STT and TTS on its internal network without published ports. Do not alter existing Ollama/Dify projects or networks during this check.

`nvidia-smi` establishes host GPU visibility. Docker runtime metadata establishes whether a GPU runtime is configured, but a read-only inspection cannot prove that a container can access the GPU; testing GPU passthrough would require starting a container and is outside this procedure. Record missing commands, permission errors and unavailable measurements as NOT ESTABLISHED rather than inferring success.

Capture the date, output and reviewer in [user-validation.md](user-validation.md). Redact sensitive host details before adding output to Git.
