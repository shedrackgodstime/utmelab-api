# Minimal Makefile for utmelab-api release workflow

# Extract version from Cargo.toml (e.g., version = "0.0.11")
VERSION := $(shell grep '^version' Cargo.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
TAG := v$(VERSION)

.PHONY: all check-version latest-release test check run release

all: help

help:
	@echo "Available targets:"
	@echo "  check-version   Verify Git tag matches Cargo version and points to HEAD"
	@echo "  latest-release  Show latest Git tag (release) on origin"
	@echo "  test            Run cargo test"
	@echo "  check           Run cargo check --release"
	@echo "  run             Run the binary (smoke test)"
	@echo "  release         Run full release pipeline and push tag"

# Verify that the current commit is tagged with the version from Cargo.toml
check-version:
	@echo "Checking version $(VERSION) and tag $(TAG)"
	@# Ensure tag exists locally
	@if ! git rev-parse $(TAG) >/dev/null 2>&1; then \
	  echo "Error: tag $(TAG) does not exist. Create it with 'git tag $(TAG)'"; \
	  exit 1; \
	fi
	@# Ensure tag points to HEAD
	@CURRENT=$$(git rev-parse HEAD); \
	TAG_COMMIT=$$(git rev-parse $(TAG)); \
	if [ "$$CURRENT" != "$$TAG_COMMIT" ]; then \
	  echo "Error: tag $(TAG) does not point to current HEAD"; \
	  exit 1; \
	fi
	@echo "Version and tag are consistent."

# Show the most recent tag on the remote
latest-release:
	@echo "Fetching remote tags..."
	@git fetch --tags origin
	@echo "Latest tag on origin:" \
	  && git describe --tags `git rev-list --tags --max-count=1`

# Run tests
test:
	@echo "Running cargo test..."
	@cargo test

# Cargo check in release mode
check:
	@echo "Running cargo check --release..."
	@cargo check --release

# Optional smoke test run
run:
	@echo "Running cargo run --release (smoke test)..."
	@cargo run --release

# Full release pipeline
release: check-version test check run
	@echo "Pushing commits and tag $(TAG) to origin..."
	@git push origin HEAD
	@git push origin $(TAG)
	@echo "Release pipeline completed. GitHub Actions will build the tag."
