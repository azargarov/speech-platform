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
	flag.Parse()
	c, e := config.Load(*path)
	if e != nil {
		return fmt.Errorf("configuration: %w", e)
	}
	if err := texttransform.ValidateConfig(c.TextTransform); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	if *check {
		return nil
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	duration := func(s string) time.Duration { d, _ := time.ParseDuration(s); return d }
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
	srv := &http.Server{Addr: net.JoinHostPort(c.ListenHost, fmt.Sprint(c.ListenPort)), Handler: gateway.HandlerWithWorkersAndText(ready, c.MaxRequestBytes, stt, tts, textService), ReadTimeout: duration(c.ReadTimeout), ReadHeaderTimeout: duration(c.ReadTimeout), WriteTimeout: duration(c.WriteTimeout), IdleTimeout: duration(c.IdleTimeout), MaxHeaderBytes: c.MaxHeaderBytes}
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
