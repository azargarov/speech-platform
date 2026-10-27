package main

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"speech-platform/internal/config"
	"speech-platform/internal/texttransform"
)

func TestSIGHUPReloadsPromptWithoutRestart(t *testing.T) {
	t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	cfg, err := config.Load("../../configs/gateway.yaml")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "prompt.txt")
	if err := os.WriteFile(path, []byte("initial prompt\n"), 0600); err != nil {
		t.Fatal(err)
	}
	cfg.TextTransform.PromptFile = path
	service, err := texttransform.New(context.Background(), cfg.TextTransform, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	initial := service.PromptSHA256()
	if err := os.WriteFile(path, []byte("updated prompt\n"), 0600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	signals := make(chan os.Signal, 1)
	done := make(chan struct{})
	go func() {
		reloadPromptOnSignal(ctx, signals, service, slog.New(slog.NewTextHandler(io.Discard, nil)))
		close(done)
	}()
	signals <- syscall.SIGHUP
	deadline := time.After(time.Second)
	for service.PromptSHA256() == initial {
		select {
		case <-deadline:
			t.Fatal("SIGHUP did not activate the updated prompt")
		case <-time.After(time.Millisecond):
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("prompt reload listener did not stop")
	}
}
