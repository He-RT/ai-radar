.PHONY: bootstrap dev check test build compose-up compose-down

bootstrap:
	./scripts/bootstrap.sh

dev:
	mise exec -- pnpm dev

check:
	./scripts/verify.sh

test:
	mise exec -- pnpm test

build:
	mise exec -- pnpm build

compose-up:
	mise exec -- pnpm compose:up

compose-down:
	mise exec -- pnpm compose:down
