package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"speech-platform/internal/config"
	"speech-platform/internal/gateway"
	"speech-platform/internal/texttransform"
	"syscall"
	"time"
)

func main() {
	if err := run(); err != nil {
		slog.New(slog.NewJSONHandler(os.Stderr, nil)).Error("gateway stopped", "error", err)
		os.Exit(1)
	}
}
func run() error {
	path := flag.String("config", "", "required YAML config path")
	check := flag.Bool("check-config", false, "validate configuration and exit")
	checkOllama := flag.Bool("check-ollama", false, "verify configured local Ollama DNS, TCP and version endpoint")
	flag.Parse()
	c, e := config.Load(*path)
	if e != nil {
		return fmt.Errorf("configuration: %w", e)
	}
	duration := func(s string) time.Duration { d, _ := time.ParseDuration(s); return d }
	if err := texttransform.ValidateConfig(c.TextTransform); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	var groqSTT *gateway.GroqSTTAdapter
	if c.GroqSTT.Enabled {
		apiKey := os.Getenv(c.GroqSTT.APIKeyEnv)
		groqSTT, e = gateway.NewGroqSTTAdapter(apiKey, c.GroqSTT.Model, duration(c.STTTimeout))
		if e != nil {
			return fmt.Errorf("configuration: %w", e)
		}
	}
	if *check {
		return nil
	}
	if *checkOllama {
		if err := texttransform.CheckLocalOllama(context.Background(), c.TextTransform); err != nil {
			return err
		}
		fmt.Println("PASS: local Ollama DNS, TCP and /api/version")
		return nil
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	stt := gateway.NewSTTProxy(c.STTURL, c.APIToken, duration(c.STTTimeout))
	tts := gateway.NewTTSProxy(c.TTSURL, c.APIToken, duration(c.TTSTimeout))
	textService, err := texttransform.New(ctx, c.TextTransform, c.APIToken, nil, logger)
	if err != nil {
		return fmt.Errorf("text transformation: %w", err)
	}
	for _, provider := range textService.MissingCredentials() {
		logger.Warn("text provider credential unavailable", "provider", provider)
	}
	if textService != nil {
		defer textService.Close()
	}
	ready := gateway.NewWorkersReadiness(stt, tts)
	handler := gateway.HandlerWithWarmupContextAndGroqSTT(ready, c.MaxRequestBytes, stt, tts, textService, duration(c.WarmupTimeout), ctx, groqSTT, c.GroqSTT.Enabled, *c.GroqSTT.Capacity)
	srv := &http.Server{Addr: net.JoinHostPort(c.ListenHost, fmt.Sprint(c.ListenPort)), Handler: gateway.WithRequestID(handler, logger), ReadTimeout: duration(c.ReadTimeout), ReadHeaderTimeout: duration(c.ReadTimeout), WriteTimeout: duration(c.WriteTimeout), IdleTimeout: duration(c.IdleTimeout), MaxHeaderBytes: c.MaxHeaderBytes}
	if c.TextTransform != nil && c.TextTransform.Enabled != nil && *c.TextTransform.Enabled {
		reloadSignals := make(chan os.Signal, 1)
		signal.Notify(reloadSignals, syscall.SIGHUP)
		defer signal.Stop(reloadSignals)
		go reloadPromptOnSignal(ctx, reloadSignals, textService, logger)
		logger.Info("text transformation prompt loaded", "sha256", textService.PromptSHA256())
	}
	errs := make(chan error, 1)
	go func() { logger.Info("gateway starting"); errs <- srv.ListenAndServe() }()
	select {
	case e := <-errs:
		if textService != nil {
			textService.Close()
		}
		if !errors.Is(e, http.ErrServerClosed) {
			return e
		}
		return nil
	case <-ctx.Done():
	}
	if textService != nil {
		textService.Close()
	}
	shutdown, cancel := context.WithTimeout(context.Background(), duration(c.ShutdownTimeout))
	defer cancel()
	return srv.Shutdown(shutdown)
}

func reloadPromptOnSignal(ctx context.Context, signals <-chan os.Signal, service *texttransform.Service, logger *slog.Logger) {
	for {
		select {
		case <-ctx.Done():
			return
		case sig, ok := <-signals:
			if !ok {
				return
			}
			if sig != syscall.SIGHUP {
				continue
			}
			if err := service.ReloadPrompt(); err != nil {
				logger.Error("text transformation prompt reload rejected", "error", err)
				continue
			}
			logger.Info("text transformation prompt reloaded", "sha256", service.PromptSHA256())
		}
	}
}
