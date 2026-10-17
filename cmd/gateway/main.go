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
	if *check {
		return nil
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	duration := func(s string) time.Duration { d, _ := time.ParseDuration(s); return d }
	srv := &http.Server{Addr: net.JoinHostPort(c.ListenHost, fmt.Sprint(c.ListenPort)), Handler: gateway.Handler(gateway.Foundation{}, c.MaxRequestBytes), ReadTimeout: duration(c.ReadTimeout), ReadHeaderTimeout: duration(c.ReadTimeout), WriteTimeout: duration(c.WriteTimeout), IdleTimeout: duration(c.IdleTimeout), MaxHeaderBytes: c.MaxHeaderBytes}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	errs := make(chan error, 1)
	go func() { logger.Info("gateway starting"); errs <- srv.ListenAndServe() }()
	select {
	case e := <-errs:
		if !errors.Is(e, http.ErrServerClosed) {
			return e
		}
		return nil
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), duration(c.ShutdownTimeout))
	defer cancel()
	return srv.Shutdown(shutdown)
}
