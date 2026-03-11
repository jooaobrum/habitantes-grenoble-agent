## Local Docker Dev

### Run
```bash
docker compose -f docker/docker-compose.yml up --build
```

### Private deps (SSH, recommended)
```bash
ssh-add -l
DOCKER_BUILDKIT=1 docker compose -f docker/docker-compose.yml build --ssh default
docker compose -f docker/docker-compose.yml up
```

### Private deps (token)
Use env vars or BuildKit secrets; never bake tokens into images.
