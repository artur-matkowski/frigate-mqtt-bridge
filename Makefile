IMAGE   ?= ghcr.io/artur-matkowski/frigate-gotify-bridge
VERSION ?= v1
GH_USER ?= artur-matkowski

.PHONY: build push release login run logs down help

help:
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build:  ## build image, tag :$(VERSION) and :latest
	docker build -t $(IMAGE):$(VERSION) -t $(IMAGE):latest .

push:  ## push :$(VERSION) and :latest to ghcr.io
	docker push $(IMAGE):$(VERSION)
	docker push $(IMAGE):latest

release: build push  ## build then push both tags

login:  ## docker login to ghcr.io using gh CLI token (requires write:packages scope)
	@gh auth status >/dev/null 2>&1 || { echo "run: gh auth login"; exit 1; }
	@gh auth token | docker login ghcr.io -u $(GH_USER) --password-stdin

run:  ## docker compose up -d (on the target VM)
	docker compose up -d

logs:  ## tail bridge logs
	docker compose logs -f bridge

down:  ## docker compose down
	docker compose down
